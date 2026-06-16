# KIRA Crawler -- Requirements installieren, crawlen, ChromaDB befuellen
#
# Verwendung:
#   .\crawl.ps1                   # Standard (4000 Seiten, depth 3)
#   .\crawl.ps1 -MaxPages 200     # Schneller Testlauf
#   .\crawl.ps1 -FillDbOnly       # Nur JSONs -> ChromaDB (kein neuer Crawl)
#   .\crawl.ps1 -InjectRatings    # Nur Modulbewertungen einpflegen
#
param(
    [int]   $MaxPages      = 4000,
    [float] $Delay         = 0.5,
    [switch]$FillDbOnly,
    [switch]$InjectRatings
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KIRA Crawler Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. pip-Abhaengigkeiten (Stamp-File, gleiche Logik wie run.ps1) -----------
$stamp   = ".pip-stamp"
$reqFile = "requirements.txt"
$needPip = $true

if ((Test-Path $stamp) -and (Test-Path $reqFile)) {
    $stampTime = (Get-Item $stamp).LastWriteTimeUtc
    $reqTime   = (Get-Item $reqFile).LastWriteTimeUtc
    if ($stampTime -ge $reqTime) { $needPip = $false }
}

if ($needPip) {
    Write-Host "[1/3] Python-Abhaengigkeiten installieren..." -ForegroundColor Cyan
    # Sicherheitscheck: requirements.txt als UTF-8 neu schreiben falls UTF-16 (BOM FF FE)
    $reqBytes = [System.IO.File]::ReadAllBytes($reqFile)
    if ($reqBytes.Length -ge 2 -and $reqBytes[0] -eq 0xFF -and $reqBytes[1] -eq 0xFE) {
        $reqText = [System.Text.Encoding]::Unicode.GetString($reqBytes, 2, $reqBytes.Length - 2)
        [System.IO.File]::WriteAllText($reqFile, $reqText, (New-Object System.Text.UTF8Encoding $false))
        Write-Host "      (requirements.txt: UTF-16 -> UTF-8 konvertiert)" -ForegroundColor Yellow
    }
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FEHLER: pip install fehlgeschlagen." -ForegroundColor Red
        exit 1
    }
    Set-Content $stamp (Get-Date -Format "o")
    Write-Host "      Abhaengigkeiten installiert." -ForegroundColor Green
} else {
    Write-Host "[1/3] pip-Abhaengigkeiten aktuell -- uebersprungen." -ForegroundColor Green
}

# -- 2. Sondermodi (kein Crawl) -----------------------------------------------
if ($InjectRatings) {
    Write-Host ""
    Write-Host "[2/3] Modulbewertungen in ChromaDB einpflegen..." -ForegroundColor Cyan
    python crawler.py --inject-ratings
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FEHLER: inject-ratings fehlgeschlagen." -ForegroundColor Red
        exit 1
    }
    Write-Host "Fertig." -ForegroundColor Green
    exit 0
}

if ($FillDbOnly) {
    Write-Host ""
    Write-Host "[2/3] Gecrawlte JSONs in ChromaDB einpflegen..." -ForegroundColor Cyan
    python crawler.py --fill-db
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FEHLER: fill-db fehlgeschlagen." -ForegroundColor Red
        exit 1
    }
    Write-Host "Fertig." -ForegroundColor Green
    exit 0
}

# -- 3. Crawlen ----------------------------------------------------------------
Write-Host ""
Write-Host "[2/3] Crawlen (max $MaxPages Seiten, delay $Delay s)..." -ForegroundColor Cyan
Write-Host "      Ziel: wiwi.kit.edu + Fachschaft + HOC/ZAK" -ForegroundColor Gray
Write-Host "      Abbrechen mit Ctrl+C (bisherige Daten bleiben erhalten)" -ForegroundColor Gray
Write-Host ""

python crawler.py --max-pages $MaxPages --delay $Delay

if ($LASTEXITCODE -ne 0) {
    Write-Host "FEHLER: Crawler fehlgeschlagen." -ForegroundColor Red
    exit 1
}

# -- 4. ChromaDB befuellen ----------------------------------------------------
Write-Host ""
Write-Host "[3/3] Gecrawlte Seiten in ChromaDB einbetten..." -ForegroundColor Cyan
Write-Host "      (Sentence-Transformer laedt beim ersten Mal ca. 500 MB)" -ForegroundColor Gray
Write-Host ""

python crawler.py --fill-db

if ($LASTEXITCODE -ne 0) {
    Write-Host "FEHLER: fill-db fehlgeschlagen." -ForegroundColor Red
    exit 1
}

# -- Fertig -------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Fertig! ChromaDB ist befuellt." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Naechste Schritte:" -ForegroundColor Cyan
Write-Host "  KIRA starten:              .\run.ps1" -ForegroundColor White
Write-Host "  Nur neu einbetten:         .\crawl.ps1 -FillDbOnly" -ForegroundColor White
Write-Host "  Modulbewertungen ergaenzen: .\crawl.ps1 -InjectRatings" -ForegroundColor White
Write-Host ""
