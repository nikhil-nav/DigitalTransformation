$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose up -d --build
Write-Output "Stack is up. Open http://localhost:3000"
