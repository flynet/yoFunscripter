; Inno Setup 6 script of yoFunscripter.
; build.ps1 passes the version: iscc /DProductVersion=1.0.0 installer\yofunscripter.iss

#if !defined(ProductVersion)
#define ProductVersion "1.0.0"
#endif
; build.ps1 passes the four-part numeric version for the file properties.
#if !defined(VersionTuple)
#define VersionTuple "1.0.0.0"
#endif
#define AppName "yoFunscripter"
#define ExeName "yoFunscripter.exe"
; The file name of the installer is the contract with the updater (SETUP_PREFIX in
; constants.py): the release asset is matched by `YoFunscripter-Setup-`, so the name is
; written in that exact case, not from AppName.
#define SetupBase "YoFunscripter-Setup"

[Setup]
AppId={{8F1B2E64-3C7A-4D95-9A21-5E7C0B4D6F18}
AppName={#AppName}
AppVersion={#ProductVersion}
AppVerName={#AppName} {#ProductVersion}
AppPublisher=flynet
AppPublisherURL=https://github.com/flynet/yoFunscripter
AppSupportURL=https://github.com/flynet/yoFunscripter/issues
AppUpdatesURL=https://github.com/flynet/yoFunscripter/releases
VersionInfoVersion={#VersionTuple}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=..\NOTICE
OutputDir=..\dist\install
OutputBaseFilename={#SetupBase}-{#ProductVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; The program writes ./scenes, ./scripts, ./result and ./work next to the exe
; (install dir defaults), so the install needs write access to {app}.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
CloseApplications=yes
RestartApplications=no
; The build is over 1 GB unpacked: the free-space check must not fail on a large disk.
DiskSpanning=no

; The installer is English only; the program itself switches language in the settings,
; so the pages of the wizard are kept in one language.
[Languages]
Name: "eng"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
eng.DeleteUserData=Delete %1 settings (window state, language, theme, folders)?

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
; The update runs the installer silently and the program closes, so the new version
; must start by itself: with ``skipifsilent`` a silent install leaves the person with a
; closed program and no sign that anything was installed.
Filename: "{app}\{#ExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall runascurrentuser

[UninstallDelete]
; The vendored pipeline keeps its intermediate artifacts in {app}\work; the user
; folders (scenes, scripts, result) are left alone.
Type: filesandordirs; Name: "{app}\work"

[Code]
{ Settings are removed only when the user asks for it. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
  LocalDataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  if UninstallSilent then
    exit;
  if MsgBox(FmtMessage(CustomMessage('DeleteUserData'), ['{#AppName}']),
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    exit;
  AppDataDir := ExpandConstant('{userappdata}\{#AppName}');
  LocalDataDir := ExpandConstant('{localappdata}\{#AppName}');
  DelTree(AppDataDir, True, True, True);
  DelTree(LocalDataDir, True, True, True);
end;
