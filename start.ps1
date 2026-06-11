# KIRA Start-Skript (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (!(Test-Path ".env")) {
    Write-Host "FEHLER: .env fehlt. Kopiere .env.example zu .env und trage die Keys ein." -ForegroundColor Red
    exit 1
}

# .env in die Prozess-Umgebung laden (Inline-Kommentare abschneiden)
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        $name  = $Matches[1].Trim()
        $value = ($Matches[2] -split '#')[0].Trim()
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

if (-not $env:GOOGLE_API_KEY -or $env:GOOGLE_API_KEY -eq "your_google_api_key_here") {
    Write-Host "FEHLER: GOOGLE_API_KEY ist nicht gesetzt (.env pruefen)." -ForegroundColor Red
    exit 1
}
if ($env:AVATAR_PROVIDER -eq "tavus" -and -not $env:TAVUS_API_KEY) {
    Write-Host "FEHLER: TAVUS_API_KEY ist nicht gesetzt (.env pruefen)." -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"

if (!(Test-Path "chroma_db")) {
    Write-Host "ChromaDB wird befuellt (einmalig)..." -ForegroundColor Cyan
    python fill_db.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FEHLER: fill_db.py fehlgeschlagen." -ForegroundColor Red
        exit 1
    }
}

Write-Host "KIRA startet auf http://localhost:8000 ..." -ForegroundColor Green
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
