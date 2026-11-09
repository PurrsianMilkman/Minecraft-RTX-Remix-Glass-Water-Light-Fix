# Makes the patched RTX Remix for Minecraft jar. Started by Make-Patched-Mod.bat. Windows PowerShell 5.1 is enough.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root 'work'
$out  = if ($env:RGF_OUT) { $env:RGF_OUT } else { Join-Path $root 'output' }   # the single-file .bat sets RGF_OUT to its own folder

# Everything downloaded is pinned: official sources, fixed versions, SHA-256 checked.
$nvidiaUrl  = 'https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases/download/v0.1.0/rtx-remix-renderer-0.1.0-202610230634-170197a.zip'
$nvidiaSize = 1031023911
$pyUrl  = 'https://www.python.org/ftp/python/3.14.0/python-3.14.0-embed-amd64.zip'
$pySha  = '8d4d3590c10449d78aa4375f534e6d5f3027d67fdc362dd1a882279db6f90fdf'
$spvUrl = 'https://conda.anaconda.org/conda-forge/win-64/spirv-tools-2026.4-h49e36cd_2.conda'
$spvSha = '933e40fe9ca887a63ef742260f0ed801cda317354806504d864764a4ed9749e1'

function Say($m) { Write-Host $m }
function Fail($m) { Write-Host ''; Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

function Download($url, $dest, $label) {
    Say "Downloading $label ..."
    # A connection that crawls (under ~1 MB/s for 20 s) is dropped and retried; the file resumes where it stopped, and a new
    # connection often lands on a faster server. Up to 8 attempts.
    for ($try = 1; $try -le 8; $try++) {
        & curl.exe -L --fail -C - -# --connect-timeout 20 --speed-limit 1000000 --speed-time 20 -o $dest $url
        if ($LASTEXITCODE -eq 0) { return }
        if ($try -lt 8) { Say "  slow or interrupted (attempt $try of 8), reconnecting and resuming ..." }
    }
    Fail "download of $label failed. Check your internet connection and run this again; it resumes."
}
function CheckSha($path, $sha, $label) {
    $got = (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower()
    if ($got -ne $sha) { Remove-Item $path -Force; Fail "$label does not match the expected checksum (got $got). It was deleted; run this again." }
}

if ($env:RGF_SELFTEST) { Write-Host "self-test ok: root=$root out=$out prebuilt=$(Test-Path (Join-Path $root 'prebuilt'))"; exit 0 }
$origJarName = 'rtx-remix-renderer-0.1.0-202610230634-170197a.jar'
$origJarSize = 1034998399
$origJarMd5  = 'c4551ac851988aa6ec5b6299c8cbd259'
function Find-LocalMod {
    $dirs = New-Object System.Collections.Generic.List[string]
    foreach ($base in @("$env:APPDATA\ModrinthApp\profiles", "$env:APPDATA\PrismLauncher\instances", "$env:USERPROFILE\curseforge\minecraft\Instances")) {
        if (Test-Path $base) {
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $dirs.Add((Join-Path $_.FullName 'mods')); $dirs.Add((Join-Path $_.FullName 'minecraft\mods')); $dirs.Add((Join-Path $_.FullName '.minecraft\mods'))
            }
        }
    }
    $dirs.Add("$env:APPDATA\.minecraft\mods"); $dirs.Add("$env:USERPROFILE\Downloads"); $dirs.Add($PSScriptRoot)
    foreach ($d in $dirs) {
        $f = Join-Path $d $origJarName
        if ((Test-Path $f) -and ((Get-Item $f).Length -eq $origJarSize)) {
            if ((Get-FileHash -Algorithm MD5 -Path $f).Hash.ToLower() -eq $origJarMd5) { return $f }
        }
    }
    return $null
}

if (-not [Environment]::Is64BitOperatingSystem) { Fail 'This needs 64-bit Windows 10 or 11.' }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Fail 'curl.exe was not found (it ships with Windows 10 version 1803 and newer).' }
if (-not (Test-Path (Join-Path $root 'prebuilt'))) { Fail 'The prebuilt folder is missing. Extract the whole zip first, do not run the .bat from inside the zip.' }

New-Item -ItemType Directory -Force -Path $work, $out | Out-Null
$free = (Get-PSDrive -Name ((Split-Path -Qualifier $root).TrimEnd(':'))).Free
if ($free -lt 4.5GB) { Fail ('About 4.5 GB of free disk space is needed here, only {0:N1} GB is free.' -f ($free / 1GB)) }

Say ''
Say '=== RTX Remix for Minecraft: glass and water light fix ==='
Say 'This patches NVIDIA''s original mod and writes ONE jar next to this file. If the original mod is already on this PC it is used, otherwise it is downloaded (about 1 GB).'
Say ''

# 1. Python (small, private copy, not installed on your system)
$pyDir = Join-Path $work 'python'
$py = Join-Path $pyDir 'python.exe'
if (-not (Test-Path $py)) {
    $pyZip = Join-Path $work 'python-embed.zip'
    if (-not (Test-Path $pyZip)) { Download $pyUrl $pyZip 'Python 3.14 (portable, 12 MB)' }
    CheckSha $pyZip $pySha 'Python'
    Expand-Archive -Path $pyZip -DestinationPath $pyDir -Force
}

# 2. SPIR-V tools (assembler, disassembler, validator)
$spvDir = Join-Path $work 'spirv-tools'
if (-not (Test-Path (Join-Path $spvDir 'spirv-val.exe'))) {
    $spvPkg = Join-Path $work 'spirv-tools.conda'
    if (-not (Test-Path $spvPkg)) { Download $spvUrl $spvPkg 'SPIR-V tools (2 MB)' }
    CheckSha $spvPkg $spvSha 'SPIR-V tools'
    & $py -I (Join-Path $PSScriptRoot 'extract_conda.py') $spvPkg $spvDir
    if ($LASTEXITCODE -ne 0) { Fail 'could not unpack the SPIR-V tools' }
}

# 3. The original mod: use the copy already on this PC if there is one (no download), otherwise NVIDIA's release zip
$localJar = Find-LocalMod
if ($localJar) {
    Say "Found your original mod, no 1 GB download needed:"
    Say "  $localJar"
    $source = @('--jar', $localJar)
} else {
    $zip = Join-Path $work 'rtx-remix-renderer-0.1.0.zip'
    if (-not (Test-Path $zip) -or (Get-Item $zip).Length -ne $nvidiaSize) { Download $nvidiaUrl $zip 'NVIDIA RTX Remix for Minecraft 0.1.0 (about 1 GB)' }
    if ((Get-Item $zip).Length -ne $nvidiaSize) { Fail 'the NVIDIA download is incomplete or different from the supported release. Delete the work folder and run this again.' }
    $source = @('--zip', $zip)
}

# 4. Patch
Say ''
Say 'Patching ...'
& $py -I (Join-Path $PSScriptRoot 'build_patched_jar.py') @source --prebuilt (Join-Path $root 'prebuilt') --spirv-tools $spvDir --out $out --work $work
if ($LASTEXITCODE -ne 0) { Fail 'the patch did not finish (see the messages above).' }

Say ''
Say '=============================================================='
Say 'All done. The patched mod (one jar) is here:'
Say "  $out"
Say ''
Say 'To install it:'
Say '  1. Close Minecraft.'
Say '  2. Open your profile''s "mods" folder and DELETE the original rtx-remix-renderer jar.'
Say '  3. Copy the new jar (the folder that just opened) into that mods folder.'
Say '  4. Start Minecraft. The first start is slower (it unpacks the runtime and builds shaders).'
Say 'In game: RTX Remix settings > "Light Transform Modifications".'
Say 'Afterwards you can delete the helper folder (RemixGlassFix-files or "work") to free about 3 GB.'
Say '=============================================================='
Start-Process explorer.exe $out
