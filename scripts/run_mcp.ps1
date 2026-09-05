$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
Set-Location -LiteralPath $ProjectRoot
& $PythonExe -m support_pilot.mcp_server --transport streamable-http

