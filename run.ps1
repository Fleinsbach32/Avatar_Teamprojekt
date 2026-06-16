# KIRA - Einziger Start-Befehl (idempotent)
# Erster Aufruf: installiert ngrok + pip-Pakete + ChromaDB
# Folgeaufrufe: ueberspringt bereits abgeschlossene Schritte
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- 1. .env pruefen --------------------------------------
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

# --- 2. ngrok pruefen / installieren ---------------------
$ngrokDir = "$env:USERPROFILE\ngrok"
$ngrokExe = "$ngrokDir\ngrok.exe"

$ngrokFound = Get-Command ngrok -ErrorAction SilentlyContinue
if (-not $ngrokFound -and !(Test-Path $ngrokExe)) {
    Write-Host "ngrok wird heruntergeladen..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $ngrokDir | Out-Null
    Invoke-WebRequest "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip" `
        -OutFile "$ngrokDir\ngrok.zip" -UseBasicParsing
    Expand-Archive -Path "$ngrokDir\ngrok.zip" -DestinationPath $ngrokDir -Force
    Remove-Item "$ngrokDir\ngrok.zip"
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -notlike "*$ngrokDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$ngrokDir", "User")
    }
    Write-Host "ngrok installiert: $ngrokExe" -ForegroundColor Green
} else {
    Write-Host "ngrok bereits vorhanden." -ForegroundColor Green
}

$env:PATH = "$ngrokDir;" + [Environment]::GetEnvironmentVariable("PATH", "User") + ";" + [Environment]::GetEnvironmentVariable("PATH", "Machine")

# --- 3. ngrok Auth-Token pruefen -------------------------
try {
    & ngrok config check *> $null
    if ($LASTEXITCODE -ne 0) { throw "no config" }
} catch {
    $token = Read-Host "ngrok Authtoken eingeben (von dashboard.ngrok.com)"
    if ($token) { & ngrok config add-authtoken $token }
}

# --- 4. pip-Abhaengigkeiten pruefen (Stamp-File) ---------
$stamp   = ".pip-stamp"
$reqFile = "requirements.txt"
$needPip = $true
if ((Test-Path $stamp) -and (Test-Path $reqFile)) {
    $stampTime = (Get-Item $stamp).LastWriteTimeUtc
    $reqTime   = (Get-Item $reqFile).LastWriteTimeUtc
    if ($stampTime -ge $reqTime) { $needPip = $false }
}
if ($needPip) {
    Write-Host "Python-Abhaengigkeiten werden installiert..." -ForegroundColor Cyan
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Host "FEHLER: pip install fehlgeschlagen." -ForegroundColor Red; exit 1 }
    Set-Content $stamp (Get-Date -Format "o")
} else {
    Write-Host "pip-Abhaengigkeiten aktuell." -ForegroundColor Green
}

$env:PYTHONIOENCODING = "utf-8"

# --- 5. ChromaDB befuellen (einmalig) --------------------
if (!(Test-Path "chroma_db")) {
    Write-Host "ChromaDB wird befuellt (einmalig, kann mehrere Minuten dauern)..." -ForegroundColor Cyan
    python scripts/fill_db.py
    if ($LASTEXITCODE -ne 0) { Write-Host "FEHLER: scripts/fill_db.py fehlgeschlagen." -ForegroundColor Red; exit 1 }
}

# --- 6. ngrok starten (alte Session beenden, feste Domain) ----------
# Stabile (reservierte) Domain aus BASE_URL ableiten, damit die im Tavus-Dashboard
# hinterlegte Custom-LLM-URL nach jedem Neustart gueltig bleibt. Ohne feste Domain
# vergibt ngrok bei jedem Start eine neue zufaellige URL -> der Voice-Pfad (Tavus
# ruft die URL serverseitig) bricht ab, waehrend der Text-Chat weiter funktioniert.
$ngrokDomain = ""
if ($env:BASE_URL) {
    $ngrokDomain = ($env:BASE_URL -replace '^https?://', '' -replace '/.*$', '').Trim()
}

# Alte ngrok-Agent-Session beenden (ngrok-Free erlaubt nur 1 gleichzeitige
# Session; eine Zombie-Instanz aus einem vorigen Lauf verhindert sonst den Start
# mit fester Domain). Idempotent: laeuft keine, passiert nichts.
$existing = Get-Process -Name ngrok -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Beende alte ngrok-Session..." -ForegroundColor Yellow
    $existing | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 1
}

Write-Host "ngrok wird gestartet..." -ForegroundColor Cyan
if ($ngrokDomain) {
    Write-Host "  feste Domain: $ngrokDomain" -ForegroundColor Gray
    Start-Process -FilePath "ngrok" -ArgumentList "http", "--domain=$ngrokDomain", "8000" -WindowStyle Hidden
} else {
    Start-Process -FilePath "ngrok" -ArgumentList "http", "8000" -WindowStyle Hidden
}

# Auf den Tunnel warten (reservierte Domain braucht ein paar Sekunden).
$url = $null
foreach ($i in 1..15) {
    Start-Sleep 1
    try {
        $tunnels = Invoke-RestMethod "http://localhost:4040/api/tunnels" -ErrorAction Stop
        $url = ($tunnels.tunnels | Where-Object { $_.proto -eq "https" }).public_url
        if ($url) { break }
    } catch {}
}
if ($url) {
    Write-Host ""
    Write-Host "ngrok URL (fuer Tavus-Dashboard): $url" -ForegroundColor Cyan
    Write-Host "Custom-LLM-URL:                  $url/tavus/llm" -ForegroundColor Cyan
    Write-Host ""
} else {
    Write-Host "ngrok URL nicht abgerufen. Moegliche Ursachen:" -ForegroundColor Yellow
    Write-Host "  - andere ngrok-Session aktiv (dashboard.ngrok.com/agents -> beenden)" -ForegroundColor Yellow
    Write-Host "  - Domain '$ngrokDomain' ist nicht reserviert (dann BASE_URL in .env leeren)" -ForegroundColor Yellow
    Write-Host "  - manuell pruefen: http://localhost:4040" -ForegroundColor Yellow
}

# --- 7. uvicorn starten ----------------------------------
Write-Host "KIRA startet auf http://localhost:8000 ..." -ForegroundColor Green
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
