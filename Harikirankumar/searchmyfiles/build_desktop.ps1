Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = "C:/Users/EKiran/AppData/Local/Programs/Python/Python311/python.exe"

& $python -m pip install -r requirements-desktop.txt

& $python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onefile `
  --name PortableOCRStudio `
  --icon assets/app_icon.ico `
  --add-data "index.html;." `
  --add-data "tutorial_quickstart.gif;." `
  --add-data "portable_tesseract;portable_tesseract" `
  desktop_app.py

Write-Host "Build complete: dist/PortableOCRStudio.exe"
