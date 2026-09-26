; Inno Setup script for the Windows installer.
; Built by CI:  ISCC /DAppVersion=x.y.z packaging\qdstar.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Same AppId as the DStar705 versions (0.2.x): installing QDStar replaces them
AppId={{7C2E3B0A-6F4D-4B1B-9E0A-D57A705D57A7}
AppName=QDStar
AppVersion={#AppVersion}
AppVerName=QDStar {#AppVersion}
AppPublisher=Manuel Alcocer Jiménez (EA7KLX)
AppPublisherURL=https://github.com/manuel-alcocer/qdstar
DefaultDirName={autopf}\QDStar
UsePreviousAppDir=no
DefaultGroupName=QDStar
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=QDStar-{#AppVersion}-windows-x64-setup
SetupIconFile=qdstar.ico
UninstallDisplayIcon={app}\qdstar.exe
UninstallDisplayName=QDStar
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
; Close a running QDStar before replacing its files
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.UninstallShortcut=Uninstall QDStar
spanish.UninstallShortcut=Desinstalar QDStar
english.AlreadyInstalled=Version %1 is already installed
spanish.AlreadyInstalled=Ya tienes instalada la versión %1
english.WhatToDo=What do you want to do? Updating keeps your settings, history and reflectors.
spanish.WhatToDo=¿Qué quieres hacer? Al actualizar se conservan tus ajustes, histórico y reflectores.
english.UpdateTo=Update to %1
spanish.UpdateTo=Actualizar a la %1
english.GoBackTo=Go back to %1
spanish.GoBackTo=Volver a la %1
english.Reinstall=Reinstall %1
spanish.Reinstall=Reinstalar la %1
english.Uninstall=Uninstall
spanish.Uninstall=Desinstalar
english.Cancel=Cancel
spanish.Cancel=Cancelar
english.DeleteData=Delete your settings, history and reflectors too?%nChoose No to keep them if you will reinstall QDStar later.
spanish.DeleteData=¿Borrar también tus ajustes, histórico y reflectores?%nSi vas a reinstalar QDStar más adelante, elige No para conservarlos.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Leftovers of the DStar705 versions
Type: filesandordirs; Name: "{autopf}\DStar705"
Type: filesandordirs; Name: "{autoprograms}\DStar705"
Type: files; Name: "{autodesktop}\DStar705.lnk"

[Files]
Source: "..\dist\qdstar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\QDStar"; Filename: "{app}\qdstar.exe"
Name: "{group}\{cm:UninstallShortcut}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\QDStar"; Filename: "{app}\qdstar.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\qdstar.exe"; Description: "{cm:LaunchProgram,QDStar}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C2E3B0A-6F4D-4B1B-9E0A-D57A705D57A7}_is1';

function InstalledValue(Name: String): String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstallKey, Name, Result) then
    RegQueryStringValue(HKLM, UninstallKey, Name, Result);
end;

// An existing installation (QDStar or the older DStar705): update, uninstall or cancel.
function InitializeSetup(): Boolean;
var
  Installed, Action, Uninstaller: String;
  OldPacked, NewPacked: Int64;
  Diff, Choice, Code: Integer;
  Labels: TArrayOfString;
begin
  Result := True;
  if WizardSilent() then
    Exit;
  Installed := InstalledValue('DisplayVersion');
  if Installed = '' then
    Exit;
  if StrToVersion(Installed, OldPacked) and StrToVersion('{#AppVersion}', NewPacked) then
    Diff := ComparePackedVersion(NewPacked, OldPacked)
  else
    Diff := 1;
  if Diff > 0 then
    Action := FmtMessage(CustomMessage('UpdateTo'), ['{#AppVersion}'])
  else if Diff < 0 then
    Action := FmtMessage(CustomMessage('GoBackTo'), ['{#AppVersion}'])
  else
    Action := FmtMessage(CustomMessage('Reinstall'), ['{#AppVersion}']);
  SetArrayLength(Labels, 3);
  Labels[0] := Action;
  Labels[1] := CustomMessage('Uninstall');
  Labels[2] := CustomMessage('Cancel');
  Choice := TaskDialogMsgBox(FmtMessage(CustomMessage('AlreadyInstalled'), [Installed]),
    CustomMessage('WhatToDo'),
    mbConfirmation, MB_YESNOCANCEL, Labels, 0);
  if Choice = IDYES then
    Exit;
  Result := False;
  if Choice = IDNO then begin
    Uninstaller := RemoveQuotes(InstalledValue('UninstallString'));
    if Uninstaller <> '' then
      Exec(Uninstaller, '', '', SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;

// On uninstall, optionally remove the user's settings and data too.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    if MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then begin
      DelTree(ExpandConstant('{userappdata}\QDStar'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\DStar705'), True, True, True);
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\QDStar');
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\DStar705');
    end;
end;
