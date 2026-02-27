# vkg-works bridge launcher
# Usage: cd to project folder, then: .\go.ps1
# Dry-run: each command from Claude is shown for your approval before running.
python "$HOME/.claude/bridge.py" `
  --dir $PSScriptRoot `
  --project "vkg.works" `
  --dry-run
