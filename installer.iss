; Инсталлятор WhisperType (Inno Setup 6). Сборка:
;   1) pyinstaller --clean --noconfirm whispertype.spec   (даёт dist\WhisperType\ — onedir)
;   2) ISCC installer.iss                                  (даёт dist_installer\WhisperTypeSetup.exe)
;
; AppId — сгенерированный один раз GUID, не менять между версиями: по нему
; Windows опознаёт «это то же приложение» при обновлении и в списке программ.
#define MyAppVersion "1.1.1"

[Setup]
AppId={{2E17A9B0-9EE0-4E3F-9EA8-2ED6D890F960}
AppName=WhisperType
AppVersion={#MyAppVersion}
AppPublisher=kirillrub108
AppPublisherURL=https://github.com/kirillrub108/whisper-type
; Только для текущего пользователя и без прав администратора — то же
; требование, что и у самого приложения (см. README, "Без прав администратора").
DefaultDirName={localappdata}\Programs\WhisperType
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Тот же именованный mutex, что и whispertype/winutil.py::acquire_single_instance —
; если приложение запущено, установка/удаление попросят сперва его закрыть,
; а не молча упадут на заблокированных файлах.
AppMutex=WhisperType.single-instance
OutputDir=dist_installer
OutputBaseFilename=WhisperTypeSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\WhisperType.exe
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\WhisperType\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\WhisperType"; Filename: "{app}\WhisperType.exe"
Name: "{autodesktop}\WhisperType"; Filename: "{app}\WhisperType.exe"; Tasks: desktopicon

[Run]
; Автозагрузку и запуск после установки решает сам пользователь — через
; чекбокс "Автозагрузка" в меню трея, а не инсталлятор: так путь к exe
; всегда берётся из места, откуда программа реально запущена.
Filename: "{app}\WhisperType.exe"; Description: "Запустить WhisperType"; Flags: nowait postinstall skipifsilent
