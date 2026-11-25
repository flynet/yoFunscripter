# Publish the release of the tagged version: create the GitHub release with its notes.
#
#   powershell -ExecutionPolicy Bypass -File tools\publish_release.ps1
#
The release is the source of the updater (`releases/latest`), so the tag must be pushed
before the release is created (`git tag v1.0.4; git push origin v1.0.4`). The token is
taken from the git credential manager, the same one `git push` uses. The release id is
written to `build\release_id.txt` for `tools\publish_upload.ps1`. The CI workflow
(`.github/workflows/release.yml`) starts on this event and builds the CPU installer.

param(
    [string]$Tag
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Set-Location (Join-Path $PSScriptRoot "..")
if (-not $Tag) { $Tag = (git describe --tags --abbrev=0).Trim() }
$version = ($Tag -replace "^v", "")
$notes = [System.IO.File]::ReadAllText((Join-Path $PWD "build\release-notes-$version.md"))
$creds = "protocol=https`nhost=github.com`n" | git credential fill
$token = ($creds | Select-String "^password=").Line.Substring(9)
$body = @{
    tag_name   = $Tag
    name       = "yoFunscripter $version"
    body       = $notes
    draft      = $false
    prerelease = $false
} | ConvertTo-Json
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$resp = Invoke-RestMethod -Method Post `
    -Uri "https://api.github.com/repos/flynet/yoFunscripter/releases" `
    -Headers @{ Authorization = "token $token"; Accept = "application/vnd.github+json" } `
    -Body $bytes -ContentType "application/json; charset=utf-8"
Write-Host "release id: $($resp.id)"
Write-Host "url: $($resp.html_url)"
Write-Host "tag: $($resp.tag_name)"
$resp.id | Out-File -Encoding ascii "build\release_id.txt"
