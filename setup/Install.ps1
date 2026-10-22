param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
function Has-App($id) {
    switch ($id) {
        'Git.Git' { return [bool]((Get-Command git -ErrorAction SilentlyContinue) -or (Test-Path "$env:ProgramFiles\Git\cmd\git.exe")) }
        'Google.Chrome' { return [bool]((Test-Path "$env:ProgramFiles\Google\Chrome\Application\chrome.exe") -or (Test-Path "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe") -or (Test-Path "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")) }
        'Microsoft.EdgeWebView2Runtime' {
            return [bool]((Test-Path "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe") -or (Test-Path "$env:LOCALAPPDATA\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe") -or (Test-Path "$env:ProgramFiles\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe"))
        }
    }
}
foreach ($id in @('Git.Git','Google.Chrome','Microsoft.EdgeWebView2Runtime')) {
    if (Has-App $id) { Write-Host "Already installed: $id"; continue }
    if ($CheckOnly) { Write-Host "Missing: $id"; continue }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Windows App Installer (winget) is missing. Install App Installer from Microsoft Store, then rerun Setup.bat.'
    }
    & winget install --id $id --exact --source winget --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if (-not (Has-App $id)) { throw "Installation of $id did not complete. Restart Windows if requested, then rerun Setup.bat." }
}
foreach ($file in @('runtime/python/python.exe','runtime/node/node.exe','runtime/ffmpeg/ffmpeg.exe','runtime/ffmpeg/ffprobe.exe','models/whisper/faster-whisper-base/model.bin','animate_flow_backend/node_modules/puppeteer/package.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $file))) { throw "Portable bundle incomplete: $file" }
}
if ($CheckOnly) { Write-Host 'Portable files checked. No installation performed.'; exit 0 }
& "$root\runtime\python\python.exe" -X utf8 "$root\bootstrap.py" setup
if ($LASTEXITCODE -ne 0) { throw 'Python dependency setup failed. Rerun Setup.bat; completed installations will be reused.' }
Write-Host 'Setup complete. Open FlowAiStudio.bat.'
