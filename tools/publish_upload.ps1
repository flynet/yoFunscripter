# Attach the installer of the local build to the release: the CUDA build of the machine,
# together with its .sha256 file.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Cuda
#   powershell -ExecutionPolicy Bypass -File tools\publish_upload.ps1
#
# The updater reads `releases/latest` and takes the asset `YoFunscripter-Setup-<version>.exe`,
# so exactly one setup file must be in the release: the CI workflow attaches its CPU build
# with the same name, and that asset is removed here after the upload. The token is taken
# from the git credential manager, the same one `git push` uses. A CUDA installer is about
# 1.7 GB, so the upload is done by `curl.exe`, which streams the file: a PowerShell string
# of that size does not fit in memory.

param(
    [long]$ReleaseId
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$creds = "protocol=https`nhost=github.com`n" | git credential fill
$token = ($creds | Select-String "^password=").Line.Substring(9)
if (-not $ReleaseId) { $ReleaseId = [long](Get-Content "build\release_id.txt" -Raw).Trim() }

$uploaded = @()
foreach ($file in Get-ChildItem "dist\install\YoFunscripter-Setup-*") {
    $out = Join-Path $env:TEMP ("asset-" + $file.Name + ".json")
    if (Test-Path $out) { Remove-Item -Force $out }
    $url = "https://uploads.github.com/repos/flynet/yoFunscripter/releases/$ReleaseId" +
           "/assets?name=" + $file.Name
    # `--data-binary @file` streams the file; the response body is the asset, saved to a
    # file so the JSON is not swallowed by the console
    & curl.exe -sS -X POST $url -H "Authorization: token $token" `
        -H "Content-Type: application/octet-stream" --data-binary "@$($file.FullName)" `
        -o $out -w "%{http_code}"
    if (-not (Test-Path $out)) { throw "curl wrote no response for $($file.Name)" }
    $body = [System.IO.File]::ReadAllText($out)
    if ($body -notmatch '"id"') { throw "upload of $($file.Name) failed: $body" }
    $asset = $body | ConvertFrom-Json
    $uploaded += $asset
    Remove-Item -Force $out
    Write-Host "uploaded $($file.Name) ($([math]::Round($file.Length / 1MB, 1)) MB) as asset $($asset.id)"
}

# the CI build of the same version is a CPU installer of the same name: two setup files
# in one release leave the updater guessing
$release = Invoke-RestMethod `
    -Uri "https://api.github.com/repos/flynet/yoFunscripter/releases/$ReleaseId" `
    -Headers @{ Authorization = "token $token" }
foreach ($asset in $release.assets) {
    if ($uploaded.id -contains $asset.id) { continue }
    if ($asset.name -like "YoFunscripter-Setup-*") {
        Invoke-RestMethod -Method Delete -Uri $asset.url `
            -Headers @{ Authorization = "token $token" } | Out-Null
        Write-Host "removed the CI asset $($asset.name) " +
                   "($([math]::Round($asset.size / 1MB, 1)) MB)"
    }
}
Write-Host "release assets:"
foreach ($asset in $uploaded) { Write-Host "  $($asset.name)" }
