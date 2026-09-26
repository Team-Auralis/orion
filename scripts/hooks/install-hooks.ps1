# Installs the ORION pre-commit hook (Obsidian vault sync rule).
# Run:  powershell -ExecutionPolicy Bypass -File scripts/hooks/install-hooks.ps1
$ErrorActionPreference = "Stop"
$src = Join-Path $PSScriptRoot "pre-commit"
$gitDir = git rev-parse --git-dir
if (-not $gitDir) { throw "not inside a git repo" }
$dst = Join-Path $gitDir "hooks\pre-commit"
Copy-Item $src $dst -Force
Write-Host "[HOOK] installed -> $dst"