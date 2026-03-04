#!/bin/bash
set -euo pipefail

# Claude Code Dictate — installer
# Installs voice dictation skill for Claude Code on macOS (Apple Silicon)

INSTALL_DIR="$HOME/.local/share/dictate"
BIN_DIR="$HOME/.local/bin"
COMMANDS_DIR="$HOME/.claude/commands"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m==>\033[0m %s\n' "$*" >&2; exit 1; }

# --- Pre-flight checks ---

[[ "$(uname)" == "Darwin" ]] || error "This tool requires macOS (uses mlx-whisper for Apple Silicon)."

command -v python3 >/dev/null 2>&1 || error "python3 not found. Install Python 3.10+ first."

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
[[ "$PYTHON_MAJOR" -ge 3 && "$PYTHON_MINOR" -ge 10 ]] || error "Python 3.10+ required (found $PYTHON_VERSION)."

if ! python3 -c "import ctypes.util; exit(0 if ctypes.util.find_library('portaudio') else 1)" 2>/dev/null; then
    if command -v brew >/dev/null 2>&1; then
        info "Installing PortAudio via Homebrew (required by sounddevice)..."
        brew install portaudio
    else
        error "PortAudio not found. Install it with: brew install portaudio"
    fi
fi

# --- Install Python script ---

info "Installing dictate.py to $INSTALL_DIR/"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/dictate.py" "$INSTALL_DIR/dictate.py"

# --- Create virtual environment & install deps ---

if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    info "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
fi

info "Installing Python dependencies (this may take a minute)..."
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet sounddevice numpy mlx-whisper

# --- Create wrapper scripts ---

info "Installing wrapper scripts to $BIN_DIR/"
mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/dictate" << 'EOF'
#!/bin/bash
exec ~/.local/share/dictate/venv/bin/python ~/.local/share/dictate/dictate.py "$@"
EOF
chmod +x "$BIN_DIR/dictate"

cat > "$BIN_DIR/dictate-editor" << 'EOF'
#!/bin/bash
# "Editor" that records voice and writes transcription to the given file.
# Designed to be used as EDITOR with Claude Code's Ctrl+G (external editor).
~/.local/bin/dictate --vad > "$1"
EOF
chmod +x "$BIN_DIR/dictate-editor"

# --- Install Claude Code skill commands ---

info "Installing Claude Code skill commands to $COMMANDS_DIR/"
mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/commands/dictate.md" "$COMMANDS_DIR/dictate.md"
cp "$SCRIPT_DIR/commands/stop-dictate.md" "$COMMANDS_DIR/stop-dictate.md"

# --- Check PATH ---

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    warn "$BIN_DIR is not in your PATH."
    warn "Add this to your shell profile (~/.zshrc or ~/.bashrc):"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# --- Done ---

ok "Installation complete!"
echo ""
echo "  Usage in Claude Code:"
echo "    /dictate        — start voice recording (with transcription menu)"
echo "    /stop-dictate   — stop recording manually"
echo ""
echo "  Voice input via Ctrl+G (recommended):"
echo "    Add this alias to your ~/.zshrc or ~/.bashrc:"
echo "      alias claude='EDITOR=dictate-editor claude'"
echo "    Then press Ctrl+G in Claude Code to dictate into the input field."
echo ""
echo "  Standalone usage:"
echo "    dictate                          — record until Enter"
echo "    dictate --vad                    — auto-stop after silence"
echo "    dictate --model small            — use smaller/faster model"
echo "    dictate --language en            — force English"
echo ""
