# ============================================================
# Setup script: Tesseract ko safe location pe copy karo
# ============================================================
# Yeh script tesseract.exe aur tessdata folder dhundh kar
# C:\Users\<username>\Tools\tesseract\ pe copy karega.
# Isse WinError 740 (elevation required) permanently fix ho jayega.
#
# How to run:
#   1. VS Code ka terminal PowerShell mein kholo
#   2. Run: powershell -ExecutionPolicy Bypass -File .\setup_tesseract.ps1
# ============================================================

$ErrorActionPreference = 'Stop'

# User ke home folder mein Tools\tesseract banao
$targetDir   = Join-Path $env:USERPROFILE 'Tools\tesseract'
$targetExe   = Join-Path $targetDir 'tesseract.exe'
$targetData  = Join-Path $targetDir 'tessdata'

Write-Host 'Tesseract dhundh rahe hain system pe...' -ForegroundColor Cyan

# Common install locations scan karo
$searchRoots = @(
    'C:\Program Files\Tesseract-OCR',
    'C:\Program Files (x86)\Tesseract-OCR',
    "$env:LOCALAPPDATA\Tesseract-OCR",
    'C:\Program Files\WindowsApps'   # winget/Microsoft Store installs
)

$foundExe  = $null
$foundData = $null

foreach ($root in $searchRoots) {
    if (-not (Test-Path $root)) { continue }

    Write-Host "  Scanning: $root"

    $exe = Get-ChildItem -Path $root -Recurse -Filter 'tesseract.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe -and -not $foundExe) {
        $foundExe = $exe.FullName
        # tessdata usually sits next to tesseract.exe
        $possibleData = Join-Path (Split-Path $exe.FullName -Parent) 'tessdata'
        if (Test-Path $possibleData) { $foundData = $possibleData }
    }
}

if (-not $foundExe) {
    Write-Host ''
    Write-Host '❌ Tesseract system pe install nahi mila.' -ForegroundColor Red
    Write-Host ''
    Write-Host 'Install karne ke liye yeh run karo:' -ForegroundColor Yellow
    Write-Host '   winget install UB-Mannheim.TesseractOCR' -ForegroundColor White
    Write-Host ''
    Write-Host 'Ya manually download karo:' -ForegroundColor Yellow
    Write-Host '   https://github.com/UB-Mannheim/tesseract/wiki' -ForegroundColor White
    Write-Host ''
    exit 1
}

Write-Host ''
Write-Host "Found tesseract.exe at: $foundExe" -ForegroundColor Green
if ($foundData) {
    Write-Host "Found tessdata at:     $foundData" -ForegroundColor Green
} else {
    Write-Host "tessdata folder NOT found alongside exe." -ForegroundColor Yellow
}

# Target directory banao
if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
}

# Binary copy karo
Write-Host ''
Write-Host "Copying to: $targetExe" -ForegroundColor Cyan
Copy-Item -Path $foundExe -Destination $targetExe -Force

# tessdata copy karo
if ($foundData) {
    Write-Host "Copying tessdata folder..." -ForegroundColor Cyan
    if (Test-Path $targetData) {
        Remove-Item -Recurse -Force $targetData
    }
    Copy-Item -Path $foundData -Destination $targetData -Recurse -Force
} else {
    Write-Host "Skipping tessdata (not found)." -ForegroundColor Yellow
}

Write-Host ''
Write-Host '=====================================================' -ForegroundColor Green
Write-Host '✅ Setup complete!' -ForegroundColor Green
Write-Host "   Binary:  $targetExe" -ForegroundColor White
Write-Host "   Data:    $targetData" -ForegroundColor White
Write-Host ''
Write-Host 'Verifying...' -ForegroundColor Cyan
& $targetExe --version
Write-Host ''
& $targetExe --list-langs
Write-Host ''
Write-Host 'Ab app.py restart kar aur image upload karke test kar.' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green