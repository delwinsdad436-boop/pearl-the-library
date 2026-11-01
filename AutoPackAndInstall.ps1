# AutoPackAndInstall.ps1 — waits for brain.jsonl, then packs & installs
param([switch]$Wait)

$Base       = "$env:USERPROFILE\TalaRipper"
$OutJson    = Join-Path $Base "output_json"
$BrainFile  = Join-Path $OutJson "brain.jsonl"
$CellsDir   = Join-Path $OutJson "cells"
$InstallDir = "$env:USERPROFILE\TalaBrain"
$DateTag    = Get-Date -Format "yyyyMMdd-HHmmss"
$ZipPath    = Join-Path $InstallDir ("tala_brain_" + $DateTag + ".zip")

function Wait-ForBrain {
  Write-Host "Waiting for brain.jsonl to exist..." -ForegroundColor Yellow
  while (-not (Test-Path $BrainFile)) { Start-Sleep 2 }
  Write-Host "brain.jsonl found. Waiting for it to stop growing..." -ForegroundColor Yellow
  do {
    $s1 = (Get-Item $BrainFile).Length
    Start-Sleep 2
    $s2 = (Get-Item $BrainFile).Length
  } while ($s1 -ne $s2)
  Write-Host "brain.jsonl is stable." -ForegroundColor Green
}

if ($Wait) { Wait-ForBrain }

# If brain.jsonl is missing (GUI didn’t build it), build one from the cells
if (-not (Test-Path $BrainFile)) {
  Write-Host "brain.jsonl missing — building from cell JSONs..." -ForegroundColor Yellow
  $cells = Get-ChildItem -Path $CellsDir -Recurse -Filter *.json | Where-Object { $_.Name -ne 'progress_sync.json' }
  if ($cells.Count -eq 0) { throw "No cells found at $CellsDir" }
  if (Test-Path $BrainFile) { Remove-Item $BrainFile -Force }
  foreach ($c in $cells) {
    (Get-Content $c.FullName -Raw) -replace "`r`n","`n" | Out-File -FilePath $BrainFile -Append -Encoding utf8
  }
}

# Make install folder, copy single master file there, and zip the lot
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item $BrainFile (Join-Path $InstallDir "brain.jsonl") -Force

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $OutJson "*") -DestinationPath $ZipPath -Force

Write-Host "Installed to $InstallDir" -ForegroundColor Green
Write-Host "ZIP created: $ZipPath" -ForegroundColor Green
