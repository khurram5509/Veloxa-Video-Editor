# Build Veloxa Video Editor V14.3.1 into a single Windows EXE.
# Run from project root:  .\build.ps1

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

# --paths . tells PyInstaller to look for our `engine` and `app` packages.
pyinstaller --noconfirm --onefile --windowed `
    --name "Veloxa-Video-Editor-V14.3.1" `
    --paths . `
    --add-data "ffmpeg;ffmpeg" `
    --add-data "app.ico;." `
    @iconFlag `
    main.py

Write-Host ""
Write-Host "Build complete: dist\Veloxa-Video-Editor-V14.3.1.exe" -ForegroundColor Green
Write-Host "Reminder: place ffmpeg.exe and ffprobe.exe in the 'ffmpeg' folder before building." -ForegroundColor Yellow
