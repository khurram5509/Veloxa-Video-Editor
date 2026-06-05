; Inno Setup script for Veloxa Video Editor V14.2.0
; Builds a single Windows installer EXE that puts the app under
; Program Files, creates Start Menu + Desktop shortcuts, and registers
; an uninstaller. Run from the project root after building the app:
;
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
;
; The output lands in .\installer\Veloxa-Video-Editor-V14.2.0-Setup.exe.
;
; V14.2.0 fix: the installed EXE is now ALWAYS named
; ``Veloxa-Video-Editor.exe`` (no version in the filename), and the
; Start Menu / Desktop shortcuts are ALWAYS named ``Veloxa Video Editor``
; (no version label). Without this, every release dropped a NEW
; versioned EXE alongside the old one in the same install dir and a
; NEW versioned shortcut alongside the old one, so users ended up with
; ``Veloxa Video Editor V13.1.0`` AND ``V14.0.0`` AND ``V14.0.1``
; all coexisting and the auto-update felt like it "didn't replace the
; old one". The [InstallDelete] block at the bottom sweeps the legacy
; versioned files / shortcuts left behind by V11..V14.0.1 installs.

#define AppName             "Veloxa Video Editor"
#define AppVersion          "14.2.0"
#define AppPublisher        "VeloxaLAB"
#define AppExeName          "Veloxa-Video-Editor.exe"
; The PyInstaller output is still versioned so dist/ shows the build
; we're packaging. Inno renames it to AppExeName at install time via
; DestName= in [Files].
#define AppBuildExe         "Veloxa-Video-Editor-V14.2.0.exe"
; AppId kept stable since V11.x so installer-driven upgrades replace
; the previous Veloxa install in place. Same GUID for the entire
; V11.x -> V14.x series. Do NOT change unless you actually want a
; side-by-side install.
#define AppId               "{{F2E1A8C4-1E5B-4C9A-9B27-VELOXA-VID-V121}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} V{#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/khurram5509/Veloxa-Video-Editor
AppSupportURL=https://github.com/khurram5509/Veloxa-Video-Editor/issues
AppUpdatesURL=https://github.com/khurram5509/Veloxa-Video-Editor/releases

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

; Force the Setup EXE's File Explorer icon to match the app icon. Without
; VersionInfo* the EXE inherits Inno Setup's default look.
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoDescription={#AppName} {#AppVersion} Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Single self-contained EXE produced by PyInstaller. The DestName flag
; renames it to the unversioned filename at install time so V14.2.0
; overwrites V14.0.1 / V13.x.x / V12.x.x even though those builds had
; versioned filenames.
Source: "dist\{#AppBuildExe}"; DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion

[InstallDelete]
; V14.2.0: clean up legacy versioned filenames + shortcuts left behind
; by V11 .. V14.0.1 installs. Without this users ended up with
; multiple "Veloxa Video Editor V<X>" entries in their Start Menu, on
; their desktop, and stale orphan EXEs in {app}.
Type: files; Name: "{app}\Veloxa-Video-Editor-V*.exe"
Type: files; Name: "{autoprograms}\Veloxa Video Editor V*.lnk"
Type: files; Name: "{autoprograms}\Uninstall Veloxa Video Editor V*.lnk"
Type: files; Name: "{autodesktop}\Veloxa Video Editor V*.lnk"

[Icons]
; Single, unversioned shortcut. Future versions overwrite this entry
; instead of adding a new one alongside it.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
; Offer to launch the app right after install.
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName} V{#AppVersion}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller --onefile extracts to %TEMP%\_MEI*; that's its own problem.
; The installed app folder is otherwise just a single EXE — clean it up.
Type: filesandordirs; Name: "{app}"
