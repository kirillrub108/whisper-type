; Инсталлятор WhisperType (Inno Setup 6). Сборка:
;   1) pyinstaller --clean --noconfirm whispertype.spec   (даёт dist\WhisperType\ — onedir)
;   2) ISCC installer.iss                                  (даёт dist_installer\WhisperTypeSetup.exe)
;
; AppId — сгенерированный один раз GUID, не менять между версиями: по нему
; Windows опознаёт «это то же приложение» при обновлении и в списке программ.
#define MyAppVersion "1.3.2"

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

[CustomMessages]
russian.AutostartTask=Запускать при входе в Windows
english.AutostartTask=Start automatically when I sign in
russian.AutostartGroup=Автозагрузка:
english.AutostartGroup=Startup:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutostartTask}"; GroupDescription: "{cm:AutostartGroup}"

[Registry]
; Автозагрузка включена по умолчанию (галочку можно снять здесь или позже в меню трея).
; Значение записывается ровно в том же формате, что и whispertype/autostart.py::_command —
; путь в кавычках: иначе is_enabled() не узнает свою запись и покажет «выключено».
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "WhisperType"; ValueData: """{app}\WhisperType.exe"""; \
    Flags: uninsdeletevalue; Tasks: autostart
; Галочка снята при повторной установке — убираем запись, оставшуюся от прошлой.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "WhisperType"; \
    Flags: deletevalue uninsdeletevalue; Tasks: not autostart

[Files]
Source: "dist\WhisperType\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\WhisperType"; Filename: "{app}\WhisperType.exe"
Name: "{autodesktop}\WhisperType"; Filename: "{app}\WhisperType.exe"; Tasks: desktopicon

[Run]
; Запуск сразу после установки предлагается, но не навязывается: при тихой
; установке (/VERYSILENT) пропускается — см. skipifsilent.
Filename: "{app}\WhisperType.exe"; Description: "Запустить WhisperType"; Flags: nowait postinstall skipifsilent
