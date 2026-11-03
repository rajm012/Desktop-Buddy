param(
    [switch]$Installer,
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

python -m pip install -e ".[windows]"
Assert-LastExitCode "Installing Windows build dependencies"
python -m PyInstaller --noconfirm --clean desktop-buddy-windows.spec
Assert-LastExitCode "Building the standalone application"

$Executable = Join-Path $ProjectRoot "dist\DesktopBuddy\DesktopBuddy.exe"

function Invoke-CodeSigning([string]$Path) {
    if (-not $Sign) {
        return
    }
    if (-not $env:WINDOWS_SIGNING_CERT -or -not $env:WINDOWS_SIGNING_PASSWORD) {
        throw "Signing requires WINDOWS_SIGNING_CERT and WINDOWS_SIGNING_PASSWORD."
    }
    $SignTool = if ($env:SIGNTOOL_PATH) { $env:SIGNTOOL_PATH } else { "signtool.exe" }
    & $SignTool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com `
        /f $env:WINDOWS_SIGNING_CERT /p $env:WINDOWS_SIGNING_PASSWORD $Path
    Assert-LastExitCode "Signing $Path"
    $Signature = Get-AuthenticodeSignature $Path
    if ($Signature.Status -ne "Valid") {
        throw "Authenticode verification failed for ${Path}: $($Signature.StatusMessage)"
    }
}

Invoke-CodeSigning $Executable

if ($Installer) {
    $Inno = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $Inno)) {
        throw "Inno Setup 6 was not found at $Inno"
    }
    & $Inno "packaging\windows\DesktopBuddy.iss"
    Assert-LastExitCode "Building the Windows installer"
    $Setup = Get-ChildItem "dist\installer\DesktopBuddy-*-setup.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $Setup) {
        throw "Inno Setup completed without producing an installer."
    }
    Invoke-CodeSigning $Setup.FullName
}
