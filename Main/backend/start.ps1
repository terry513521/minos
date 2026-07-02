$ErrorActionPreference = "Stop"

$BackendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostAddr = if ($env:MAIN_HOST) { $env:MAIN_HOST } else { "0.0.0.0" }
$Port = if ($env:MAIN_PORT) { $env:MAIN_PORT } else { "8000" }

Set-Location $BackendRoot

if (-not (Test-Path ".venv")) {
    Write-Host "==> Creating virtual environment"
    python -m venv .venv
    & .\.venv\Scripts\pip install -r requirements.txt
}

$env:MAIN_HOST = $HostAddr
$env:MAIN_PORT = $Port

Write-Host "==> Starting control plane on ${HostAddr}:${Port}"
& .\.venv\Scripts\uvicorn app.main:app --host $HostAddr --port $Port @args
