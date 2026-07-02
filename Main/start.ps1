$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostAddr = if ($env:MAIN_HOST) { $env:MAIN_HOST } else { "0.0.0.0" }
$Port = if ($env:MAIN_PORT) { $env:MAIN_PORT } else { "8000" }

Write-Host "==> Building frontend"
Set-Location (Join-Path $Root "frontend")
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run build

Write-Host "==> Starting control plane on ${HostAddr}:${Port} (API + static UI)"
Set-Location (Join-Path $Root "backend")
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    & .\.venv\Scripts\pip install -r requirements.txt
}

$env:MAIN_HOST = $HostAddr
$env:MAIN_PORT = $Port
$env:MAIN_SERVE_FRONTEND = "true"
& .\.venv\Scripts\uvicorn app.main:app --host $HostAddr --port $Port @args
