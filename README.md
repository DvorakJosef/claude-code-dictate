# claude-code-dictate

Voice dictation skill for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Records audio from your microphone and transcribes it locally using [Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon — no API calls, everything runs on-device.

## Requirements

- macOS on Apple Silicon (M1/M2/M3/M4)
- Python 3.10+
- Microphone access

## Install

```bash
git clone https://github.com/AlfredoProgworksss/claude-code-dictate.git
cd claude-code-dictate
./install.sh
```

The installer will:
1. Create a Python venv at `~/.local/share/dictate/` with `mlx-whisper`, `sounddevice`, and `numpy`
2. Install wrapper scripts to `~/.local/bin/`
3. Install `/dictate` and `/stop-dictate` slash commands to `~/.claude/commands/`

## Usage

### Inside Claude Code

Type `/dictate` to start voice recording. The recording auto-stops after a few seconds of silence (VAD). You can also type `/stop-dictate` to stop it manually.

The transcribed text is sent directly to Claude as your message.

### Standalone CLI

```bash
# Record until you press Enter
dictate

# Auto-stop after silence (voice activity detection)
dictate --vad

# Use a specific model
dictate --model small    # tiny | small | turbo (default) | large-v3

# Force a language
dictate --language en

# Fixed duration recording
dictate --duration 10
```

### Editor integration

You can use dictation as an external editor for Claude Code's `Ctrl+G`:

```bash
EDITOR=dictate-editor claude
```

Then press `Ctrl+G` to dictate instead of typing.

## Models

| Name       | Model                                    | Speed   | Quality |
|------------|------------------------------------------|---------|---------|
| `tiny`     | `mlx-community/whisper-tiny`             | Fastest | Basic   |
| `small`    | `mlx-community/whisper-small-mlx`        | Fast    | Good    |
| `turbo`    | `mlx-community/whisper-large-v3-turbo`   | Medium  | Great   |
| `large-v3` | `mlx-community/whisper-large-v3-mlx`    | Slow    | Best    |

Models are downloaded automatically on first use from Hugging Face.

## Uninstall

```bash
rm -rf ~/.local/share/dictate
rm ~/.local/bin/dictate ~/.local/bin/dictate-editor
rm ~/.claude/commands/dictate.md ~/.claude/commands/stop-dictate.md
```

## License

MIT
