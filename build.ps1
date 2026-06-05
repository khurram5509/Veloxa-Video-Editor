# Build Veloxa Video Editor V14.3.7 as a Windows --onedir bundle.
# Run from project root:  .\build.ps1
#
# V14.3.7: switched from --onefile to --onedir because --onefile's
# bootloader extracts ~400 MB of bundled code to %TEMP%\_MEI{random}
# at every launch — right after an in-app update, Windows Defender
# is still scanning the freshly-written EXE and holds file handles,
# causing the bootloader's LoadLibrary("python314.dll") to fail with
# "The specified module could not be found". The user had to close
# and re-launch for it to work.
#
# --onedir keeps python314.dll + every other support file permanently
# beside the EXE, so launches are instant and AV-race-free. The Inno
# Setup script (installer.iss) now copies the entire bundle directory
# instead of a single EXE.

$ErrorActionPreference = "Stop"

if (-not (Test-Path .\venv)) {
    python -m venv venv
}
.\venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pillow

# Generate the .ico (used as the EXE icon in File Explorer).
python make_icon.py

$iconFlag = @()
if (Test-Path .\app.ico) {
    $iconFlag = @("--icon", "app.ico")
}

# --onedir: produces dist\Veloxa-Video-Editor-V14.3.7\
#   ├── Veloxa-Video-Editor-V14.3.7.exe   (small launcher)
#   ├── _internal\python314.dll
#   ├── _internal\Qt6Core.dll
#   └── ...several hundred support files
# --paths . lets PyInstaller resolve our local `engine` and `app`
# packages without an installed-distribution lookup.
pyinstaller --noconfirm --onedir --windowed `
    --name "Veloxa-Video-Editor-V14.3.7" `
    --paths . `
    --add-data "ffmpeg;ffmpeg" `
    --add-data "app.ico;." `
    @iconFlag `
    main.py

Write-Host ""
Write-Host "Build complete: dist\Veloxa-Video-Editor-V14.3.7\" -ForegroundColor Green
Write-Host "Reminder: place ffmpeg.exe and ffprobe.exe in the 'ffmpeg' folder before building." -ForegroundColor Yellow
