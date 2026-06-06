; Inno Setup script for Veloxa Video Editor V14.4.0
; Builds a single Windows installer EXE that puts the app under
; Program Files, creates Start Menu + Desktop shortcuts, and registers
; an uninstaller. Run from the project root after building the app:
;
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
;
; The output lands in .\installer\Veloxa-Video-Editor-V14.4.0-Setup.exe.
;
; V14.4.0 fix: the installed EXE is now ALWAYS named
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
#define AppVersion          "14.4.0"
#define AppPublisher        "VeloxaLAB"
#define AppExeName          "Veloxa-Video-Editor.exe"
; The PyInstaller output is still versioned so dist/ shows the build
; we're packaging. Inno renames it to AppExeName at install time via
; DestName= in [Files].
#define AppBuildExe         "Veloxa-Video-Editor-V14.4.0.exe"
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
; V14.4.0: PyInstaller now produces a --onedir bundle at
; dist\Veloxa-Video-Editor-V14.4.0\ containing the launcher EXE plus a
; sibling _internal\ directory with python314.dll, Qt6Core.dll, and
; every other support file. Copy the whole tree to {app}; the launcher
; EXE is renamed at install time to the unversioned name so the desktop
; / start-menu shortcuts and the in-app update flow keep working.
Source: "dist\Veloxa-Video-Editor-V{#AppVersion}\{#AppBuildExe}"; \
    DestDir: "{app}"; DestName: "{#AppExeName}"; Flags: ignoreversion
Source: "dist\Veloxa-Video-Editor-V{#AppVersion}\_internal\*"; \
    DestDir: "{app}\_internal"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; V14.4.0: clean up legacy versioned filenames + shortcuts left behind
; by V11 .. V14.4.0 installs (which were single-EXE --onefile builds).
; Without this users would end up with multiple "Veloxa Video Editor
; V<X>" entries in their Start Menu, on their desktop, and stale orphan
; EXEs in {app}. Also wipe any pre-existing _internal\ from a V14.4.0+
; install in case the dependency tree changed between releases (e.g. a
; PyQt6 minor bump dropped a DLL we no longer need).
Type: files; Name: "{app}\Veloxa-Video-Editor-V*.exe"
Type: files; Name: "{autoprograms}\Veloxa Video Editor V*.lnk"
Type: files; Name: "{autoprograms}\Uninstall Veloxa Video Editor V*.lnk"
Type: files; Name: "{autodesktop}\Veloxa Video Editor V*.lnk"
Type: filesandordirs; Name: "{app}\_internal"

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
; V14.4.0: --onedir lays down the EXE + _internal\ subtree under {app}.
; Sweep the entire install dir on uninstall so no orphan files remain
; (the launcher EXE, every _internal\ DLL, the ffmpeg subtree, the
; app.ico). The legacy single-EXE %TEMP%\_MEI* extract paths are no
; longer created so there's nothing to clean up there.
Type: filesandordirs; Name: "{app}"
