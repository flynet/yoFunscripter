# Download ffmpeg.exe and ffprobe.exe into tools\ffmpeg (build.ps1 copies them into the
# build as bin\ffmpeg.exe, bin\ffprobe.exe, so the program never asks the machine).
#
#   powershell -ExecutionPolicy Bypass -File tools\fetch_ffmpeg.ps1
#
# The archive is the official Windows x64 build of the FFmpeg project (BtbN builds, GPL
# license, the same binaries the program drives with -progress and -filter_complex).
# The zip is over 80 MB, and only two files of it are kept.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "tools\ffmpeg"
$url = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"

New-Item -ItemType Directory -Force -Path $target | Out-Null
$zip = Join-Path $env:TEMP "ffmpeg-win64-gpl.zip"

Write-Host "Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zip -UserAgent "yoFunscripter"

# The archive keeps the binaries in ffmpeg-master-latest-win64-gpl/bin.
$dir = Join-Path $env:TEMP "ffmpeg-extract"
if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
Expand-Archive -Path $zip -DestinationPath $dir

$found = Get-ChildItem -Path $dir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $found) { throw "ffmpeg.exe not in the archive" }
$bin = $found.DirectoryName
Copy-Item -Force (Join-Path $bin "ffmpeg.exe") (Join-Path $target "ffmpeg.exe")
Copy-Item -Force (Join-Path $bin "ffprobe.exe") (Join-Path $target "ffprobe.exe")
Remove-Item -Force $zip
Remove-Item -Recurse -Force $dir

foreach ($name in @("ffmpeg.exe", "ffprobe.exe")) {
    $path = Join-Path $target $name
    if (-not (Test-Path $path)) { throw "$name not extracted" }
    $version = (& $path -version 2>&1 | Select-Object -First 1)
    # `$name:` in a double-quoted string is a drive-qualified variable reference, so the
    # name is put in braces: the runner stops the build on a parse error
    Write-Host "$($name): $version"
}
Write-Host "FFmpeg binaries: $target"
