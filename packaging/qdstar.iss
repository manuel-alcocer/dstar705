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
english.OtherOptions=Other options…
spanish.OtherOptions=Otras opciones…
english.NowPerUser=QDStar is installed only for you
spanish.NowPerUser=QDStar está instalado solo para ti
english.NowAllUsers=QDStar is installed for all users
spanish.NowAllUsers=QDStar está instalado para todos los usuarios
english.SwitchInfo=Installing for all users puts QDStar in Program Files and needs administrator permission. Changing it keeps your settings, history and reflectors. Close QDStar first.
spanish.SwitchInfo=Instalar para todos los usuarios pone QDStar en Archivos de programa y necesita permiso de administrador. Al cambiarlo se conservan tus ajustes, histórico y reflectores. Cierra QDStar antes.
english.ForAllUsers=Install for all users
spanish.ForAllUsers=Instalar para todos los usuarios
english.ForMeOnly=Install only for me
spanish.ForMeOnly=Instalar solo para mí
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
; In-app update (qdstar/winupdate.py): silent install, then QDStar starts again
Filename: "{app}\qdstar.exe"; Flags: nowait runasoriginaluser; Check: RelaunchRequested

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C2E3B0A-6F4D-4B1B-9E0A-D57A705D57A7}_is1';

function InstalledValue(Name: String): String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstallKey, Name, Result) then
    RegQueryStringValue(HKLM, UninstallKey, Name, Result);
end;

// QDStar updating itself passes /SILENT /RELAUNCH=1
function RelaunchRequested(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

// Install this version in the other mode (per user <-> all users) and then remove
// the existing copy. The new install runs first: when it fails or the UAC prompt
// is declined, the existing copy stays as it was. Settings and data live in the
// user's profile and are not touched (a silent uninstall never deletes them).
procedure SwitchInstallMode(ToAllUsers: Boolean; OldUninstaller: String);
var
  Params: String;
  Code: Integer;
  Done: Boolean;
begin
  Params := ' /SILENT /NORESTART /RELAUNCH=1 /LANG=' + ActiveLanguage();
  if ToAllUsers then
    // Setup asks for administrator rights by itself and this call waits for it
    Done := Exec(ExpandConstant('{srcexe}'), '/ALLUSERS' + Params, '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code)
  else
    // This Setup runs elevated: the per-user install must belong to the user who started it
    Done := ExecAsOriginalUser(ExpandConstant('{srcexe}'), '/CURRENTUSER' + Params, '', SW_SHOWNORMAL,
      ewWaitUntilTerminated, Code);
  if Done and (Code = 0) and (OldUninstaller <> '') then
    Exec(OldUninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

// An existing installation (QDStar or the older DStar705): update, switch between
// per-user and all-users installation, uninstall or cancel.
function InitializeSetup(): Boolean;
var
  Installed, Action, Uninstaller, Ignored: String;
  OldPacked, NewPacked: Int64;
  Diff, Choice, Code: Integer;
  Labels: TArrayOfString;
  PerUser: Boolean;
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
  Labels[1] := CustomMessage('OtherOptions');
  Labels[2] := CustomMessage('Cancel');
  Choice := TaskDialogMsgBox(FmtMessage(CustomMessage('AlreadyInstalled'), [Installed]),
    CustomMessage('WhatToDo'),
    mbConfirmation, MB_YESNOCANCEL, Labels, 0);
  if Choice = IDYES then
    Exit;
  Result := False;
  if Choice <> IDNO then
    Exit;
  // A task dialog takes three buttons at most: the less common actions go in a second one
  PerUser := RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', Ignored);
  Uninstaller := RemoveQuotes(InstalledValue('UninstallString'));
  if PerUser then begin
    Labels[0] := CustomMessage('ForAllUsers');
    Action := CustomMessage('NowPerUser');
  end else begin
    Labels[0] := CustomMessage('ForMeOnly');
    Action := CustomMessage('NowAllUsers');
  end;
  Labels[1] := CustomMessage('Uninstall');
  Choice := TaskDialogMsgBox(Action, CustomMessage('SwitchInfo'), mbConfirmation, MB_YESNOCANCEL, Labels, 0);
  if Choice = IDYES then
    SwitchInstallMode(PerUser, Uninstaller)
  else if (Choice = IDNO) and (Uninstaller <> '') then
    Exec(Uninstaller, '', '', SW_SHOWNORMAL, ewNoWait, Code);
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
