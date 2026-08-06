$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'

if (-not (Test-Path $Python)) {
    throw "找不到 Windows Python 3.11：$Python（這是打包電腦才需要，夥伴電腦不需要）"
}

Set-Location $Root
& $Python -m pip install --upgrade pyinstaller playwright
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit code $LASTEXITCODE)" }
& $Python -m PyInstaller --noconfirm --clean 'ZaoshenRPA.spec'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit code $LASTEXITCODE)" }

$IsccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    Write-Host '正在安裝 Inno Setup（只用於產生安裝程式）...'
    winget install --id JRSoftware.InnoSetup -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup install failed (exit code $LASTEXITCODE)" }
    $Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw 'Inno Setup 安裝後仍找不到 ISCC.exe' }

& $Iscc (Join-Path $Root 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed (exit code $LASTEXITCODE)" }
# Windows PowerShell 5.1 may decode a UTF-8-without-BOM script using the
# system code page. Locate the one versioned installer without relying on a
# Chinese literal in this script's final verification step.
$Output = Get-ChildItem (Join-Path $Root 'dist-installer\*-1.2.3.exe') -File |
    Where-Object { $_.Name -notmatch '^unins' } |
    Select-Object -First 1
if (-not $Output) { throw 'Build finished but the expected *-1.2.3.exe installer was not found' }
Write-Host "`n完成：$Output" -ForegroundColor Green
