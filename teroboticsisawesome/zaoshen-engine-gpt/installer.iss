#define MyAppName "造神引擎 RPA"
#define MyAppVersion "1.2.3"
#define MyAppExeName "造神引擎RPA.exe"

[Setup]
AppId={{A9764711-647C-4BE8-9E96-C322615BD39F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\ZaoshenRPA
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=dist-installer
OutputBaseFilename=造神引擎RPA安裝程式-1.2.3
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "其他選項："; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "啟動 {#MyAppName}"; Flags: nowait postinstall skipifsilent
