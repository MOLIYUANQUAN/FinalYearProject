# Install flyctl for the current user, then tell you the next step.
$ErrorActionPreference = "Stop"
Write-Host "Installing flyctl..."
Invoke-Expression (Invoke-RestMethod "https://fly.io/install.ps1")
$candidates = @(
    (Join-Path $env:USERPROFILE ".fly\bin"),
    (Join-Path $env:LOCALAPPDATA "fly\bin")
)
foreach ($bin in $candidates) {
    if (Test-Path (Join-Path $bin "flyctl.exe")) {
        $env:Path = "$bin;$env:Path"
        break
    }
}
if (-not (Get-Command flyctl -ErrorAction SilentlyContinue)) {
    throw "flyctl still not on PATH. Open a new terminal and try: flyctl version"
}
Write-Host ""
Write-Host "Next:"
Write-Host "  flyctl auth login"
Write-Host "  .\.venv\Scripts\python.exe scripts\deploy_fly.py"
