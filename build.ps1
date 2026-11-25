# Build of yoFunscripter: the version, the program, the installer.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1           # CPU build (small)
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Cuda     # GPU build for a CUDA box
#
# Output: dist\yoFunscripter\ (the program with bin\ffmpeg.exe, bin\ffprobe.exe,
# models\best.pt, configs\) and dist\install\YoFunscripter-Setup-<version>.exe with its
# .sha256 file. Run "uv sync" first.
#
# -Cuda replaces the CPU torch wheels of the venv with the cu126 wheels of the PyTorch
# index before PyInstaller runs: the CUDA build is over 2.5 GB, so the default build of
# the repository ships CPU wheels and the GPU machine gets its own build.

param(
    [switch]$Cuda
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)

# --- 1. the version from the git tag -----------------------------------------
# git writes to stderr when the repository has no tags; the native command must not
# stop the script, so the preference is relaxed for this call.
$version = "1.0.0"
$ErrorActionPreference = "Continue"
$tag = (git describe --tags --abbrev=0) 2>$null
if ($LASTEXITCODE -eq 0 -and $tag) {
    $version = ($tag -replace "^v", "").Trim()
}
$ErrorActionPreference = "Stop"
$LASTEXITCODE = 0
Write-Host "Version: $version"

$versionFile = "src\yofunscripter\_version.py"
$versionLines = @(
    '"""Version of the application.',
    '',
    '``build.ps1`` writes this file from ``git describe --tags``; in development',
    'it stays ``1.0.0``. The updater compares this value with the latest release.',
    '"""',
    '',
    "VERSION = `"$version`""
)
[System.IO.File]::WriteAllText((Join-Path $PWD $versionFile), ($versionLines -join "`n"), $utf8)

# --- 2. the version resource for the .exe ------------------------------------
$numbers = ($version -replace "[^0-9.]", ".").Split(".")
$parts = @(0, 0, 0, 0)
for ($i = 0; $i -lt 4 -and $i -lt $numbers.Length; $i++) {
    if ($numbers[$i] -match "^\d+$") { $parts[$i] = [int]$numbers[$i] }
}
$tuple = "(" + ($parts -join ", ") + ")"
$tupleText = ($parts -join ".")

New-Item -ItemType Directory -Force -Path "build" | Out-Null
$template = Get-Content "version_info.template.txt" -Raw
$filled = $template.Replace("VERSION_TUPLE", $tuple).Replace("VERSION_STRING", $version)
[System.IO.File]::WriteAllText((Join-Path $PWD "build\version_info.txt"), $filled, $utf8)

# --- 3. the torch wheels of the venv -----------------------------------------
# The default venv has the CPU wheels (torchcpu index of pyproject.toml). A CUDA box
# needs the cu126 wheels: they are taken from the PyTorch index, not from PyPI.
if ($Cuda) {
    Write-Host "CUDA build: installing the cu126 wheels of torch and torchvision"
    $ErrorActionPreference = "Continue"
    uv pip install --reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($code -ne 0) { throw "torch CUDA install failed" }
    # the check of the wheels: a CPU torch in the venv makes a CUDA build that cannot use
    # the GPU, and the installer is over 2.5 GB, so building it is pointless
    $wheels = (& ".venv\Scripts\python.exe" -c "import torch; print(torch.__version__)" 2>$null)
    Write-Host "torch in the venv: $wheels"
    if ($wheels -notmatch "cu126") { throw "the venv has $wheels, not the cu126 wheels" }
}

# --- 4. PyInstaller ----------------------------------------------------------
# uv and PyInstaller write progress on stderr: NativeCommandError must not stop the
# script, the exit code is the real check. `--no-sync` keeps the venv as it is: a plain
# `uv run` syncs the project and puts the CPU torch wheels back over the cu126 ones.
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
$ErrorActionPreference = "Continue"
uv run --no-sync pyinstaller --clean --noconfirm yofunscripter.spec
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0) { throw "PyInstaller failed" }

# --- 5. ffmpeg and ffprobe in {app}\bin -------------------------------------
# The program drives ffmpeg with `-progress` and `-filter_complex_script`, so it needs
# the full build with ffprobe; the imageio-ffmpeg binary has no ffprobe. The copy is
# shipped into the build, so the machine of the user needs nothing installed.
$binDir = "dist\yoFunscripter\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

function Get-Bin([string]$name) {
    # 1. tools\ffmpeg (tools\fetch_ffmpeg.ps1), 2. the ffmpeg of the machine
    $local = Join-Path $PSScriptRoot "tools\ffmpeg\$name"
    if (Test-Path $local) { return $local }
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @("C:\ffmpeg\bin", "D:\ffmpeg\bin")) {
        $candidate = Join-Path $dir $name
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

foreach ($name in @("ffmpeg.exe", "ffprobe.exe")) {
    $path = Get-Bin $name
    if (-not $path) {
        Write-Host "$name not found: downloading the official build"
        & powershell -ExecutionPolicy Bypass -File "tools\fetch_ffmpeg.ps1"
        $path = Join-Path $PSScriptRoot "tools\ffmpeg\$name"
        if (-not (Test-Path $path)) { throw "$name not found and not downloaded" }
    }
    Copy-Item -Force $path (Join-Path $binDir $name)
    Write-Host "$name from: $path"
}

# --- 6. Inno Setup ----------------------------------------------------------
$iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
if (-not $iscc) {
    # the per-user install created by winget without administrator rights
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
}
if (-not $iscc) {
    Write-Warning "Inno Setup not found: the installer is not built. Install it with: winget install -e --id JRSoftware.InnoSetup"
    exit 0
}

& $iscc "/DProductVersion=$version" "/DVersionTuple=$tupleText" "installer\yofunscripter.iss"
$code = $LASTEXITCODE
if ($code -ne 0) { throw "Inno Setup failed" }

# --- 7. SHA-256 of the installer -------------------------------------------
# The prefix YoFunscripter-Setup- is the contract with the updater (constants.py).
$setup = "dist\install\YoFunscripter-Setup-$version.exe"
if (-not (Test-Path $setup)) { throw "installer not produced: $setup" }
$hash = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
$hashFile = "$setup.sha256"
# No byte-order mark: the file is plain text, so `sha256sum -c` and Get-FileHash
# comparisons read it as is (Set-Content -Encoding utf8 adds a BOM in Windows 5.1).
[System.IO.File]::WriteAllText($hashFile, "$hash  $(Split-Path $setup -Leaf)`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Installer: $setup"
Write-Host "SHA-256:   $hash"
