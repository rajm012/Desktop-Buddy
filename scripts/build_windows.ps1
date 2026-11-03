param(
    [switch]$Installer,
    [switch]$Sign
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

python -m pip install -e ".[windows]"
python -m PyInstaller --noconfirm --clean desktop-buddy-windows.spec

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
}

Invoke-CodeSigning $Executable

if ($Installer) {
    $Inno = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $Inno)) {
        throw "Inno Setup 6 was not found at $Inno"
    }
    & $Inno "packaging\windows\DesktopBuddy.iss"
    $Setup = Get-ChildItem "dist\installer\DesktopBuddy-*-setup.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    Invoke-CodeSigning $Setup.FullName
}
