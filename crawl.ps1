# Thin-Wrapper: leitet an scripts/crawl.ps1 weiter.
# Die eigentliche Crawler-Logik liegt unter scripts/ (siehe TP1-Aufraeumen),
# dieser Wrapper haelt den gewohnten Aufruf ".\crawl.ps1" am Root verfuegbar.
#
# Beispiele:
#   .\crawl.ps1
#   .\crawl.ps1 -MaxPages 200
#   .\crawl.ps1 -FillDbOnly
#   .\crawl.ps1 -InjectRatings
& "$PSScriptRoot\scripts\crawl.ps1" @args
