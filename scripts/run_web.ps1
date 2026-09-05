$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StreamlitExe = Join-Path $ProjectRoot ".venv\Scripts\streamlit.exe"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
Set-Location -LiteralPath $ProjectRoot
& $StreamlitExe run src/support_pilot/ui.py

