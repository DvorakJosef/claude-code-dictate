#!/usr/bin/env python3
"""Voice dictation tool — records from microphone and transcribes via Whisper on Apple Silicon."""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time

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


BAR_WIDTH = 20
BAR_FILLED = "\u2501"   # ━
BAR_EMPTY = "\u2591"    # ░
BAR_REF_SECS = 60       # Visual bar fills over 60s (timer keeps counting beyond)


def display_progress(stop_event, start_time, max_secs, vad_state):
    """Show a live progress bar on stderr during recording."""
    if not sys.stderr.isatty():
        return

    speech_started, silent_frames, total_frames, sample_rate, cal_secs = vad_state

    while not stop_event.is_set():
        elapsed = time.monotonic() - start_time
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60

        progress = min(elapsed / max_secs, 1.0)
        filled = int(BAR_WIDTH * progress)
        bar = BAR_FILLED * filled + BAR_EMPTY * (BAR_WIDTH - filled)

        # Determine status label
        if speech_started is None:
            status = "recording..."
        elif total_frames[0] / sample_rate < cal_secs:
            status = "calibrating..."
        elif speech_started[0]:
            if silent_frames[0] > 0:
                status = "silence..."
            else:
                status = "speech"
        else:
            status = "listening..."

        line = f"\r\033[31m\u2b24\033[0m {mins}:{secs:02d} {bar}  {status}"
        sys.stderr.write(f"{line}\033[K")
        sys.stderr.flush()

        stop_event.wait(0.1)

    # Clear the progress line
    sys.stderr.write("\r\033[K")
    sys.stderr.flush()


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
    bar_max = duration if duration else BAR_REF_SECS

    # Build VAD state tuple for progress display (None = no VAD)
    if vad:
        vad_display = (vad_speech_started, vad_silent_frames, vad_total_frames,
                       sample_rate, CALIBRATION_SECS)
    else:
        vad_display = (None, None, [0], sample_rate, 0)

    # Announce before opening the stream so the mic doesn't pick it up
    if vad:
        subprocess.run(
            ["say", "-r", "200", "recording started"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    with stream:
        start_time = time.monotonic()

        # Start progress bar
        progress_thread = threading.Thread(
            target=display_progress,
            args=(stop_event, start_time, bar_max, vad_display),
            daemon=True,
        )
        progress_thread.start()

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
            pass

        safety_timer.cancel()
        # Wait for progress bar to clear
        progress_thread.join(timeout=0.5)

    # Announce recording ended (in background so it doesn't block transcription)
    if vad:
        subprocess.Popen(
            ["say", "-r", "200", "recording ended"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

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
