# Regenerates the intro page PDF from the live built page.
# Run AFTER `python scripts/build.py` has been run from the repo root.

$ErrorActionPreference = 'Stop'

$repo  = Resolve-Path "$PSScriptRoot\.."
$page  = Join-Path $repo 'site\intro\index.html'
$out   = Join-Path $repo 'static\intro\vkg-intro.pdf'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'

if (-not (Test-Path $page))   { throw "Built page not found: $page  (run `python scripts/build.py` first)" }
if (-not (Test-Path $chrome)) { throw "Chrome not found at $chrome" }

$uri = ([System.Uri](Get-Item $page).FullName).AbsoluteUri

& $chrome --headless --disable-gpu --no-sandbox `
  --print-to-pdf="$out" --print-to-pdf-no-header `
  --virtual-time-budget=15000 $uri

Write-Host "Wrote $out"
