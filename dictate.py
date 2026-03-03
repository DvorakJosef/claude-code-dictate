#!/usr/bin/env python3
"""Voice dictation tool — records from microphone and transcribes via Whisper on Apple Silicon."""

import argparse
import os
import signal
import subprocess
import sys
import threading

import numpy as np
import sounddevice as sd

MODELS = {
    "tiny": "mlx-community/whisper-tiny",
    "small": "mlx-community/whisper-small-mlx",
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}

SAMPLE_RATE = 16000
MAX_RECORDING = 300  # Safety timeout in seconds (5 minutes)
CALIBRATION_SECS = 0.5  # Ambient noise measurement period
DEFAULT_SILENCE_TIMEOUT = 2.0  # Seconds of silence after speech to auto-stop


def err(*args, **kwargs):
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


def record_audio(
    sample_rate: int,
    duration: float | None = None,
    stop_file: str | None = None,
    vad: bool = False,
    silence_timeout: float = DEFAULT_SILENCE_TIMEOUT,
) -> np.ndarray:
    """Record audio from microphone until stopped by VAD, duration, stop file, Enter, or Ctrl+C."""
    chunks: list[np.ndarray] = []
    stop_event = threading.Event()

    # VAD state (mutated from callback thread)
    vad_speech_started = [False]
    vad_silent_frames = [0]
    vad_threshold = [0.015]
    vad_calibration: list[float] = []
    vad_total_frames = [0]

    def callback(indata, frames, time_info, status):
        if status:
            err(f"  (audio status: {status})")
        chunks.append(indata.copy())

        if not vad or stop_event.is_set():
            return

        vad_total_frames[0] += frames
        rms = float(np.sqrt(np.mean(indata**2)))

        # Calibration phase: measure ambient noise
        if vad_total_frames[0] / sample_rate < CALIBRATION_SECS:
            vad_calibration.append(rms)
            return

        # Set threshold once after calibration
        if vad_calibration:
            ambient = sum(vad_calibration) / len(vad_calibration)
            vad_threshold[0] = max(ambient * 3, 0.005)
            vad_calibration.clear()

        # Detect speech and silence
        if rms > vad_threshold[0]:
            vad_speech_started[0] = True
            vad_silent_frames[0] = 0
        elif vad_speech_started[0]:
            vad_silent_frames[0] += frames
            if vad_silent_frames[0] / sample_rate >= silence_timeout:
                stop_event.set()

    try:
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
        )
    except sd.PortAudioError as e:
        msg = str(e)
        if "permission" in msg.lower() or "denied" in msg.lower():
            err("Error: Microphone permission denied.")
            err("  Grant access in System Settings > Privacy & Security > Microphone.")
        else:
            err(f"Error opening audio input: {e}")
        sys.exit(1)

    def wait_for_enter():
        try:
            with open("/dev/tty", "r") as tty:
                tty.readline()
        except (EOFError, OSError):
            return
        stop_event.set()

    def watch_stop_file():
        while not stop_event.is_set():
            if os.path.exists(stop_file):
                try:
                    os.unlink(stop_file)
                except OSError:
                    pass
                stop_event.set()
                return
            stop_event.wait(0.2)

    timeout = duration if duration else MAX_RECORDING

    with stream:
        if duration:
            err(f"Recording for {duration:.0f}s... (Ctrl+C to stop early)")
        elif vad:
            err("Recording... (auto-stop after silence)")
            # After calibration: play beep to signal mic is live
            def _signal_ready():
                subprocess.run(
                    ["afplay", "/System/Library/Sounds/Tink.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            threading.Timer(CALIBRATION_SECS, _signal_ready).start()
        elif stop_file:
            err("Recording...")
        else:
            err("Recording... press Enter to stop.")

        if not duration:
            t = threading.Thread(target=wait_for_enter, daemon=True)
            t.start()

        if stop_file:
            sf = threading.Thread(target=watch_stop_file, daemon=True)
            sf.start()

        safety_timer = threading.Timer(timeout, stop_event.set)
        safety_timer.daemon = True
        safety_timer.start()

        try:
            stop_event.wait()
        except KeyboardInterrupt:
            err()  # newline after ^C

        safety_timer.cancel()

    if not chunks:
        return np.array([], dtype="float32")

    audio = np.concatenate(chunks, axis=0).flatten()
    return audio


def transcribe(audio: np.ndarray, model_name: str, language: str | None) -> str:
    """Transcribe audio array using mlx-whisper."""
    import mlx_whisper

    hf_repo = MODELS[model_name]
    err(f"Transcribing with {model_name} ({hf_repo})...")

    kwargs: dict = {"path_or_hf_repo": hf_repo}
    if language:
        kwargs["language"] = language

    result = mlx_whisper.transcribe(audio, **kwargs)
    return result["text"].strip()


def copy_to_clipboard(text: str):
    """Copy text to macOS clipboard via pbcopy."""
    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Record from microphone and transcribe using Whisper on Apple Silicon.",
    )
    parser.add_argument(
        "--model",
        choices=MODELS.keys(),
        default="turbo",
        help="Whisper model size (default: turbo)",
    )
    parser.add_argument(
        "--language",
        metavar="LANG",
        help="Force language code, e.g. cs or en (default: auto-detect)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        metavar="SECS",
        help="Record for fixed duration (seconds) instead of waiting for Enter",
    )
    parser.add_argument(
        "--stop-file",
        metavar="PATH",
        help="Watch for this file to appear — stop recording when it does",
    )
    parser.add_argument(
        "--vad",
        action="store_true",
        help="Auto-stop recording after silence (voice activity detection)",
    )
    parser.add_argument(
        "--silence-timeout",
        type=float,
        default=DEFAULT_SILENCE_TIMEOUT,
        metavar="SECS",
        help=f"Seconds of silence before auto-stop (default: {DEFAULT_SILENCE_TIMEOUT})",
    )
    args = parser.parse_args()

    # Check for audio input devices
    try:
        sd.query_devices(kind="input")
    except sd.PortAudioError:
        err("Error: No audio input device found.")
        sys.exit(1)

    # Clean up stale stop file from previous run
    if args.stop_file and os.path.exists(args.stop_file):
        os.unlink(args.stop_file)

    audio = record_audio(
        SAMPLE_RATE,
        args.duration,
        args.stop_file,
        args.vad,
        args.silence_timeout,
    )

    duration = len(audio) / SAMPLE_RATE
    err(f"Recorded {duration:.1f}s of audio.")

    if duration < 0.3:
        err("Recording too short, skipping transcription.")
        sys.exit(0)

    # Ignore Ctrl+C during transcription — we already have audio, finish the job
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    text = transcribe(audio, args.model, args.language)

    if not text:
        err("No speech detected.")
        sys.exit(0)

    print(text)

    if sys.stdout.isatty():
        copy_to_clipboard(text)
        err("(Copied to clipboard)")


if __name__ == "__main__":
    main()
