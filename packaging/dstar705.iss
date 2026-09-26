; Inno Setup script for the Windows installer.
; Built by CI:  ISCC /DAppVersion=x.y.z packaging\dstar705.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7C2E3B0A-6F4D-4B1B-9E0A-D57A705D57A7}
AppName=DStar705
AppVersion={#AppVersion}
AppPublisher=Manuel Alcocer Jiménez (EA7KLX)
AppPublisherURL=https://github.com/manuel-alcocer/dstar705
DefaultDirName={autopf}\DStar705
DefaultGroupName=DStar705
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=DStar705-{#AppVersion}-windows-x64-setup
SetupIconFile=dstar705.ico
UninstallDisplayIcon={app}\dstar705.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\dstar705\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\DStar705"; Filename: "{app}\dstar705.exe"
Name: "{autodesktop}\DStar705"; Filename: "{app}\dstar705.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\dstar705.exe"; Description: "{cm:LaunchProgram,DStar705}"; Flags: nowait postinstall skipifsilent
