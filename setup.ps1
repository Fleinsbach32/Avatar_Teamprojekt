# KIRA Setup-Skript
# Installiert ngrok falls nicht vorhanden und richtet die Umgebung ein.

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force

# ── ngrok ────────────────────────────────────────────────
$ngrokDir = "$env:USERPROFILE\ngrok"
$ngrokExe = "$ngrokDir\ngrok.exe"

if (!(Get-Command ngrok -ErrorAction SilentlyContinue) -and !(Test-Path $ngrokExe)) {
    Write-Host "ngrok wird heruntergeladen..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $ngrokDir | Out-Null
    Invoke-WebRequest "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip" `
        -OutFile "$ngrokDir\ngrok.zip" -UseBasicParsing
    Expand-Archive -Path "$ngrokDir\ngrok.zip" -DestinationPath $ngrokDir -Force
    Remove-Item "$ngrokDir\ngrok.zip"

    # Dauerhaft zum PATH hinzufügen
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -notlike "*$ngrokDir*") {
        [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$ngrokDir", "User")
    }
    Write-Host "ngrok installiert: $ngrokExe" -ForegroundColor Green
} else {
    Write-Host "ngrok bereits vorhanden." -ForegroundColor Green
}

# PATH in aktueller Session laden
$env:PATH = "$ngrokDir;" + [Environment]::GetEnvironmentVariable("PATH", "User") + ";" + [Environment]::GetEnvironmentVariable("PATH", "Machine")

# ── ngrok Auth-Token ─────────────────────────────────────
$token = Read-Host "ngrok Authtoken eingeben (Enter zum Ueberspringen)"
if ($token) {
    & $ngrokExe config add-authtoken $token
}

# ── Python venv ───────────────────────────────────────────
Write-Host "`nPython-Abhaengigkeiten werden installiert..." -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "`nSetup abgeschlossen!" -ForegroundColor Green
Write-Host "Backend starten:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
Write-Host "Tunnel starten:   ngrok http 8000"
