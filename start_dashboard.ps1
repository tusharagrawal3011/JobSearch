# Starts the local API (FastAPI) and the Next.js dashboard in separate windows.
# Usage:  ./start_dashboard.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "cd '$root'; .\.venv\Scripts\Activate.ps1; uvicorn backend.api.main:app --host 127.0.0.1 --port 8010"
)

Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "cd '$root\dashboard'; if (-not (Test-Path .env.local)) { Copy-Item .env.local.example .env.local }; npm run dev"
)

Write-Host "API  -> http://127.0.0.1:8010"
Write-Host "Dashboard -> http://localhost:3000"
