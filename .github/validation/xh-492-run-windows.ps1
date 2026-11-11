# Parent-run helper; no installation, workflow dispatch, or remote write.
# Run with pwsh.exe from the reviewed xh checkout on Windows.
#Requires -Version 7.3
param([string]$EvidenceDir = (Join-Path (Get-Location) 'xh-492-windows-evidence'))

$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Native Windows is required; Unix PowerShell is not validation.' }
if (-not (Test-Path 'tests/curl_powershell.rs')) { throw 'Run from the reviewed xh repository root.' }
if (Test-Path $EvidenceDir) { throw 'Use a fresh evidence directory to avoid stale passing records.' }
New-Item -ItemType Directory -Path $EvidenceDir | Out-Null
$EvidenceDir = (Resolve-Path $EvidenceDir).Path
$env:XH_POWERSHELL_EVIDENCE_DIR = $EvidenceDir
$env:CARGO_INCREMENTAL = '0'
$env:CARGO_PROFILE_DEV_DEBUG = '0'
$env:RUSTUP_TOOLCHAIN = '1.97.1'
$env:NO_PROXY = '127.0.0.1,localhost,::1'

@(
    "UTC: $([DateTime]::UtcNow.ToString('o'))"
    "GitHub SHA: $env:GITHUB_SHA"
    "HEAD: $(git rev-parse HEAD)"
    'Git status:'
    (git status --porcelain)
    "rustc: $(rustc --version)"
    "cargo: $(cargo --version)"
    'Native executables:'
    (Get-Command powershell.exe, pwsh.exe, curl.exe | Format-List Name, Source | Out-String)
) | Set-Content -Encoding utf8 (Join-Path $EvidenceDir 'provenance.txt')

cargo test --locked --no-default-features --features rustls --test curl_powershell -- --ignored --nocapture 2>&1 |
    Tee-Object -FilePath (Join-Path $EvidenceDir 'native-test.log')
$testExit = $LASTEXITCODE

if (Test-Path 'target/debug/xh.exe') {
    Get-FileHash 'target/debug/xh.exe' -Algorithm SHA256 |
        Format-List | Out-String |
        Set-Content -Encoding utf8 (Join-Path $EvidenceDir 'binary-sha256.txt')
}
if ($testExit -ne 0) { throw "Native Windows matrix failed with exit code $testExit. Retain all evidence." }

$records = @(Get-ChildItem $EvidenceDir -Filter '*.json')
if ($records.Count -ne 177) { throw "Expected 177 JSON records, got $($records.Count); matrix is incomplete." }
$checks = 0
foreach ($file in $records) {
    $record = Get-Content -Raw $file.FullName | ConvertFrom-Json
    if ($null -ne $record.PSObject.Properties['expected']) {
        $expected = ConvertTo-Json -InputObject $record.expected -Depth 100 -Compress
        $actual = ConvertTo-Json -InputObject $record.actual -Depth 100 -Compress
        if ($expected -cne $actual) { throw "Byte mismatch in $($file.Name)" }
        if ($null -ne $record.PSObject.Properties['exit_success'] -and -not $record.exit_success) {
            throw "curl failed in $($file.Name)"
        }
        $checks++
    }
}
if ($checks -ne 170) { throw "Expected 170 exact comparisons, got $checks." }
"PASS: native Windows matrix; 84 argv cases, 84 single-request bodies, 2 negative controls; 177 JSON records." |
    Tee-Object -FilePath (Join-Path $EvidenceDir 'verification.txt')
