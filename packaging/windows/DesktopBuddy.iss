#define MyAppName "Desktop Buddy"
#define MyAppVersion "1.8.0"
#define MyAppPublisher "Desktop Buddy"
#define MyAppExeName "DesktopBuddy.exe"

[Setup]
AppId={{C7D7A49A-753E-44EC-981C-96DDC08BF488}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Desktop Buddy
DefaultGroupName=Desktop Buddy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=DesktopBuddy-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\..\dist\DesktopBuddy\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Desktop Buddy"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\Desktop Buddy"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Desktop Buddy"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Choice: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Choice := SuppressibleMsgBox(
      'Remove Desktop Buddy settings, reminder history, focus history, logs, plugins, and cached data?',
      mbConfirmation,
      MB_YESNO,
      IDNO
    );
    if Choice = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\desktop-buddy'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\desktop-buddy'), True, True, True);
    end;
  end;
end;
