param(
    [Parameter(Mandatory = $true)]
    [string]$ApplicationPath,

    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [string]$OutputPath = "windows-release-validation.md"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "Windows release validation must run on Windows 10 or Windows 11."
}

function Resolve-RequiredFile([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label was not found at $Path."
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Get-VerifiedSignature([string]$Path) {
    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne "Valid") {
        throw "Invalid Authenticode signature for ${Path}: $($signature.StatusMessage)"
    }
    if (-not $signature.SignerCertificate) {
        throw "The Authenticode signature for $Path has no signer certificate."
    }
    if (-not $signature.TimeStamperCertificate) {
        throw "The Authenticode signature for $Path has no trusted timestamp."
    }
    return $signature
}

function Escape-Markdown([object]$Value) {
    if ($null -eq $Value) {
        return ""
    }
    return ([string]$Value).Replace("|", "\|").Replace("`r", " ").Replace("`n", " ")
}

function Add-ChecklistSection(
    [System.Collections.Generic.List[string]]$Lines,
    [string]$Title,
    [string[]]$Checks
) {
    $Lines.Add("## $Title")
    $Lines.Add("")
    $Lines.Add("| Check | Result | Notes |")
    $Lines.Add("| --- | --- | --- |")
    foreach ($check in $Checks) {
        $Lines.Add("| $(Escape-Markdown $check) | [ ] Pass [ ] Fail | |")
    }
    $Lines.Add("")
}

$application = Resolve-RequiredFile $ApplicationPath "Desktop Buddy executable"
$installer = Resolve-RequiredFile $InstallerPath "Desktop Buddy installer"
$output = [IO.Path]::GetFullPath($OutputPath)

$applicationSignature = Get-VerifiedSignature $application
$installerSignature = Get-VerifiedSignature $installer

$smoke = Start-Process -FilePath $application -ArgumentList "--version" `
    -PassThru -Wait
if ($smoke.ExitCode -ne 0) {
    throw "Packaged executable smoke test failed with exit code $($smoke.ExitCode)."
}

$operatingSystem = Get-CimInstance Win32_OperatingSystem
$computer = Get-CimInstance Win32_ComputerSystem
$videoControllers = @(Get-CimInstance Win32_VideoController)
$desktop = Get-ItemProperty "HKCU:\Control Panel\Desktop"
$logPixelsProperty = $desktop.PSObject.Properties["LogPixels"]
$systemDpi = if ($logPixelsProperty) { [int]$logPixelsProperty.Value } else { 96 }
$systemScale = [math]::Round(($systemDpi / 96.0) * 100)
$perMonitorDpiKeys = @(
    Get-ChildItem "HKCU:\Control Panel\Desktop\PerMonitorSettings" `
        -ErrorAction SilentlyContinue
)

$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Desktop Buddy Windows release validation")
$lines.Add("")
$lines.Add("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$lines.Add("")
$lines.Add("> Complete every row on a supported Windows 10 machine and a supported Windows 11 machine. Keep both reports with the release evidence.")
$lines.Add("")
$lines.Add("## Machine evidence")
$lines.Add("")
$lines.Add("| Field | Value |")
$lines.Add("| --- | --- |")
$lines.Add("| OS | $(Escape-Markdown $operatingSystem.Caption) |")
$lines.Add("| Version | $(Escape-Markdown $operatingSystem.Version) |")
$lines.Add("| Build | $(Escape-Markdown $operatingSystem.BuildNumber) |")
$lines.Add("| Manufacturer | $(Escape-Markdown $computer.Manufacturer) |")
$lines.Add("| Model | $(Escape-Markdown $computer.Model) |")
$lines.Add("| PowerShell | $(Escape-Markdown $PSVersionTable.PSVersion) |")
$lines.Add("| System DPI at capture | ${systemDpi} (${systemScale}%) |")
$lines.Add("| Per-monitor DPI registry entries | $($perMonitorDpiKeys.Count) |")
$lines.Add("")
$lines.Add("### Display adapters at capture")
$lines.Add("")
$lines.Add("| Adapter | Driver | Current mode |")
$lines.Add("| --- | --- | --- |")
foreach ($controller in $videoControllers) {
    $mode = "$($controller.CurrentHorizontalResolution)x$($controller.CurrentVerticalResolution)"
    $lines.Add("| $(Escape-Markdown $controller.Name) | $(Escape-Markdown $controller.DriverVersion) | $(Escape-Markdown $mode) |")
}
$lines.Add("")
$lines.Add("## Automated artifact preflight")
$lines.Add("")
$lines.Add("| Artifact | Signature | Signer | Timestamp signer |")
$lines.Add("| --- | --- | --- | --- |")
$lines.Add("| DesktopBuddy.exe | Valid | $(Escape-Markdown $applicationSignature.SignerCertificate.Subject) | $(Escape-Markdown $applicationSignature.TimeStamperCertificate.Subject) |")
$lines.Add("| Installer | Valid | $(Escape-Markdown $installerSignature.SignerCertificate.Subject) | $(Escape-Markdown $installerSignature.TimeStamperCertificate.Subject) |")
$lines.Add("")
$lines.Add("Packaged executable `--version` smoke test: **Pass**")
$lines.Add("")

Add-ChecklistSection $lines "DPI and transparent rendering" @(
    "100% scaling: transparent background, correct size, no black rectangle",
    "125% scaling: transparent background, correct size, no black rectangle",
    "150% scaling: transparent background, correct size, no black rectangle",
    "175% scaling: transparent background, correct size, no black rectangle",
    "200% scaling: transparent background, correct size, no black rectangle",
    "Mixed-DPI monitors: move repeatedly between displays without geometry or scale drift",
    "Window remains absent from the taskbar and does not steal keyboard focus"
)

Add-ChecklistSection $lines "Displays and window behavior" @(
    "Primary and secondary monitor placement",
    "Monitor with a negative desktop origin",
    "Taskbar positioned on the top, bottom, left, and right edges",
    "Monitor disconnect and reconnect while Desktop Buddy is running",
    "Always-on-top behavior",
    "Click-through enablement and recovery through tray or CLI",
    "Dragging and throwing across monitor boundaries",
    "Browser and terminal perching",
    "Exclusive-fullscreen application lowers Desktop Buddy and disables perching"
)

Add-ChecklistSection $lines "Desktop services and IPC" @(
    "Tray icon and all core tray actions",
    "Reminder/focus notifications",
    "Reminder audio",
    "Startup-folder autostart after sign-out or reboot",
    "Battery and AC-power state",
    "Second launch controls the existing process",
    "Concurrent launch does not create a duplicate buddy"
)

Add-ChecklistSection $lines "Installer lifecycle" @(
    "Clean per-user install without Python",
    "Upgrade from the previous supported installer",
    "Preserve-data uninstall keeps settings, history, logs, plugins, and cache",
    "Purge-data uninstall removes settings, history, logs, plugins, and cache",
    "Reinstall after preserve-data uninstall restores expected settings",
    "Reinstall after purge-data uninstall starts with defaults"
)

Add-ChecklistSection $lines "Security and release decision" @(
    "Get-AuthenticodeSignature remains Valid after download to the test machine",
    "SmartScreen behavior and publisher identity reviewed",
    "No unexpected elevation prompt during install, launch, upgrade, or uninstall",
    "All failures have linked issues and documented workarounds",
    "Release approved only after both Windows 10 and Windows 11 reports pass"
)

$outputDirectory = Split-Path -Parent $output
if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}
$lines | Set-Content -LiteralPath $output -Encoding utf8
Write-Host "Validation report created at $output"
