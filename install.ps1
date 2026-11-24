# Job-o-Matic installer for Windows.
#
#   Run it in PowerShell. Or from any prompt:
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/JR91387/jobomatic-reusme-skills-database/main/install.ps1 | iex"
#   irm https://raw.githubusercontent.com/JR91387/jobomatic-reusme-skills-database/main/install.ps1 | iex
#
# What it does:
#   1. Installs (or upgrades) the job-o-matic package: with uv if you have it,
#      otherwise with "py -3 -m pip install --user" (needs Python 3.12 or newer).
#   2. Starts Job-o-Matic in the background. On its first run it adds itself to the
#      Start Menu and opens in your browser.
# Safe to run again: it upgrades in place and never touches your data folder.

$ErrorActionPreference = 'Stop'
$Package = 'job-o-matic'

function Stop-Install([string]$Message) {
    throw "Stopped: $Message"
}

$binDir = $null
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Installing Job-o-Matic with uv: uv tool install --upgrade $Package"
    & uv tool install --upgrade $Package
    if ($LASTEXITCODE -ne 0) { Stop-Install "uv could not install $Package (see the message above)." }
    $binDir = (& uv tool dir --bin | Out-String).Trim()
} else {
    $py = $null
    $pyArgs = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $py = 'py'
        $pyArgs = @('-3')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $py = 'python'
    } else {
        Stop-Install "Python 3.12 or newer is needed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') or install uv (https://docs.astral.sh/uv/), then run this again."
    }
    & $py @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Stop-Install "Job-o-Matic needs Python 3.12 or newer. Install it from https://www.python.org/downloads/ or install uv (https://docs.astral.sh/uv/), then run this again."
    }
    Write-Host "Installing Job-o-Matic with pip: $py $($pyArgs -join ' ') -m pip install --user --upgrade $Package"
    & $py @pyArgs -m pip install --user --upgrade $Package
    if ($LASTEXITCODE -ne 0) { Stop-Install "pip could not install $Package (see the message above)." }
    $binDir = (& $py @pyArgs -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))" | Out-String).Trim()
}

$found = Get-Command job-o-matic -ErrorAction SilentlyContinue
if ($found) {
    $cmd = $found.Source
} elseif ($binDir -and (Test-Path (Join-Path $binDir 'job-o-matic.exe'))) {
    $cmd = Join-Path $binDir 'job-o-matic.exe'
    Write-Host "Tip: add $binDir to your PATH so you can type job-o-matic in a terminal."
} else {
    Stop-Install "installed, but the job-o-matic command was not found in $binDir."
}

Write-Host "Starting Job-o-Matic: $cmd --open"
Start-Process -FilePath $cmd -ArgumentList '--open' -WindowStyle Hidden
Write-Host "Done. Job-o-Matic opens in your browser and is in the Start Menu from now on."
