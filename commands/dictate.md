---
description: Record voice from microphone and transcribe with Whisper
allowed-tools: Bash(~/.local/bin/dictate:*)
---

!`~/.local/bin/dictate --vad --silence-timeout 3 --stop-file /tmp/claude-dictate-stop`

After the command finishes, display the transcription text to the user in a blockquote (> ...). Detect the language of the transcription and use that language for all UI text. Then use AskUserQuestion with these options (shown here in English, but translate to match the transcription language):
1. "Use as input" — treat the transcription as if the user typed it and respond to it directly
2. "Modify" — let the user edit/correct the transcription before using it as input
3. "Something else" — the user can type a free-form instruction about what to do with the transcription
