param(
    [string]$Python = "python",
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "gps-another",
    "app.py"
)

if ($OneFile) {
    $args = @("-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onefile", "--name", "gps-another", "app.py")
}

& $Python @args

Write-Host ""
Write-Host "Build complete."
Write-Host "Onedir executable: dist\gps-another\gps-another.exe"
Write-Host "Place a local .env file next to the executable, or set ORS_API_KEY as a user environment variable."
