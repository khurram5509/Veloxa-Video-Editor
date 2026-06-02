; Inno Setup script for Veloxa Video Editor V14.0.1
; Builds a single Windows installer EXE that puts the app under
; Program Files, creates Start Menu + Desktop shortcuts, and registers
; an uninstaller. Run from the project root after building the app:
;
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
;
; The output lands in .\installer\Veloxa-Video-Editor-V14.0.1-Setup.exe.

#define AppName        "Veloxa Video Editor"
#define AppVersion     "14.0.1"
#define AppPublisher   "VeloxaLAB"
#define AppExeName     "Veloxa-Video-Editor-V14.0.1.exe"
; AppId kept stable across V12.x AND V13.x so installer-driven upgrades
; replace the previous Veloxa install in place. Same GUID since V11.x —
; do NOT change unless you actually want a side-by-side install.
#define AppId          "{{F2E1A8C4-1E5B-4C9A-9B27-VELOXA-VID-V121}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} V{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://veloxalab.local/
AppSupportURL=https://veloxalab.local/
AppUpdatesURL=https://veloxalab.local/

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName} V{#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}

; Allow per-user OR per-machine; user picks at install time.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; The bundled EXE already contains FFmpeg + Qt + everything else, so
; the installer just needs to drop one file (~388 MB) plus shortcuts.
; Compress aggressively for a smaller setup binary.
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Write outside the Dropbox tree first to avoid Dropbox's sync agent
; locking the file during rsrc updates ("EndUpdateResource failed").
; A post-build step copies the finished installer back to .\installer\.
OutputDir={#GetEnv("LOCALAPPDATA")}\VeloxaVD-Build\installer
OutputBaseFilename=Veloxa-Video-Editor-V{#AppVersion}-Setup
SetupIconFile=app.ico
WizardStyle=modern
ShowLanguageDialog=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Single self-contained EXE produced by PyInstaller.
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu (lives in Programs root since DisableProgramGroupPage=yes).
Name: "{autoprograms}\{#AppName} V{#AppVersion}"; Filename: "{app}\{#AppExeName}"
; Optional desktop shortcut.
Name: "{autodesktop}\{#AppName} V{#AppVersion}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; Uninstall shortcut alongside the app, makes it findable when users go
; looking through Programs without opening Settings → Apps.
Name: "{autoprograms}\Uninstall {#AppName} V{#AppVersion}"; Filename: "{uninstallexe}"

[Run]
; Offer to launch the app right after install.
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} V{#AppVersion}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller --onefile extracts to %TEMP%\_MEI*; that's its own problem.
; The installed app folder is otherwise just a single EXE — clean it up.
Type: filesandordirs; Name: "{app}"
