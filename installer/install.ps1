# Makes the patched RTX Remix for Minecraft jar. Started by Make-Patched-Mod.bat. Windows PowerShell 5.1 is enough.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root 'work'
$out  = if ($env:RGF_OUT) { $env:RGF_OUT } else { Join-Path $root 'output' }   # the single-file .bat sets RGF_OUT to its own folder

# Everything downloaded is pinned: official sources, fixed versions, checksums.
# Supported mod builds, newest first (NVIDIA's unmodified jars). Only the newest is ever downloaded; an older one is used if it is already on the PC.
$mods = @(
    @{ Version = '0.1.1'; Name = 'rtx-remix-renderer-0.1.1-202611060211-7d2ba9f.jar'; Size = 1035282184; Md5 = '0b9c4d5f272fc4627d48ba6c636f2ef5';
       Url = 'https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases/download/v0.1.1/rtx-remix-renderer-0.1.1-202611060211-7d2ba9f.jar' },
    @{ Version = '0.1.0'; Name = 'rtx-remix-renderer-0.1.0-202610230634-170197a.jar'; Size = 1034998399; Md5 = 'c4551ac851988aa6ec5b6299c8cbd259'; Url = $null }
)
$pyUrl  = 'https://www.python.org/ftp/python/3.14.0/python-3.14.0-embed-amd64.zip'
$pySha  = '8d4d3590c10449d78aa4375f534e6d5f3027d67fdc362dd1a882279db6f90fdf'
$spvUrl = 'https://conda.anaconda.org/conda-forge/win-64/spirv-tools-2026.4-h49e36cd_2.conda'
$spvSha = '933e40fe9ca887a63ef742260f0ed801cda317354806504d864764a4ed9749e1'

function Say($m) { Write-Host $m }
function Fail($m) { Write-Host ''; Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

# Small files: curl, with stall detection and retries.
function Download($url, $dest, $label) {
    Say "Downloading $label ..."
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

# The original mod may already be on this PC (Modrinth, Prism, CurseForge, .minecraft, Downloads): then nothing has to be downloaded.
function Find-LocalMod {
    $dirs = New-Object System.Collections.Generic.List[string]
    foreach ($base in @("$env:APPDATA\ModrinthApp\profiles", "$env:APPDATA\PrismLauncher\instances", "$env:USERPROFILE\curseforge\minecraft\Instances")) {
        if (Test-Path $base) {
            Get-ChildItem $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $dirs.Add((Join-Path $_.FullName 'mods')); $dirs.Add((Join-Path $_.FullName 'minecraft\mods')); $dirs.Add((Join-Path $_.FullName '.minecraft\mods'))
            }
        }
    }
    $dirs.Add("$env:APPDATA\.minecraft\mods"); $dirs.Add("$env:USERPROFILE\Downloads"); $dirs.Add($PSScriptRoot); $dirs.Add($work)
    # A jar placed next to this file (any file name) is used first: this is the way to patch without any download.
    $sideDirs = @($env:RGF_OUT, (Get-Location).Path) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    foreach ($d in $sideDirs) {
        foreach ($f in (Get-ChildItem -LiteralPath $d -Filter '*.jar' -File -ErrorAction SilentlyContinue)) {
            if ($f.Name -like '*LightFix*') { continue }
            foreach ($m in $mods) {
                if ($f.Length -eq $m.Size -and (Get-FileHash -Algorithm MD5 -Path $f.FullName).Hash.ToLower() -eq $m.Md5) { return @{ Path = $f.FullName; Version = $m.Version } }
            }
        }
    }
    foreach ($m in $mods) {                      # newest version first
        foreach ($d in $dirs) {
            $f = Join-Path $d $m.Name
            if ((Test-Path $f) -and ((Get-Item $f).Length -eq $m.Size)) {
                if ((Get-FileHash -Algorithm MD5 -Path $f).Hash.ToLower() -eq $m.Md5) { return @{ Path = $f; Version = $m.Version } }
            }
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
Say 'This patches NVIDIA''s original mod and writes ONE jar next to this file, named ...-LightFix.jar. A mod jar placed next to this file is used first; else one already on this PC; else it is downloaded (about 1 GB).'
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

# 3. The original mod: the copy already on this PC if there is one, otherwise NVIDIA's newest jar
$found = Find-LocalMod
if ($found) {
    Say "Found the original mod (version $($found.Version)), no download needed:"
    Say "  $($found.Path)"
    $jar = $found.Path
} else {
    $latest = $mods[0]
    $jar = Join-Path $work $latest.Name
    Say "Downloading NVIDIA RTX Remix for Minecraft $($latest.Version) (about 1 GB), over 8 connections like a browser ..."
    for ($try = 1; $try -le 3; $try++) {
        & $py -I (Join-Path $PSScriptRoot 'fastdl.py') $latest.Url $jar $latest.Size 8
        if ($LASTEXITCODE -eq 0) { break }
        if ($try -eq 3) { Fail 'the download did not finish. Check your internet connection and run this again; it resumes.' }
        Say '  interrupted, resuming ...'
    }
    if ((Get-Item $jar).Length -ne $latest.Size) { Fail 'the NVIDIA download is incomplete. Delete the work folder and run this again.' }
}

# 4. Patch
Say ''
Say 'Patching ...'
& $py -I (Join-Path $PSScriptRoot 'build_patched_jar.py') --jar $jar --prebuilt (Join-Path $root 'prebuilt') --spirv-tools $spvDir --out $out --work $work
if ($LASTEXITCODE -ne 0) { Fail 'the patch did not finish (see the messages above).' }

Say ''
Say '=============================================================='
Say 'All done. The patched mod (one jar) is here:'
Say "  $out"
Say ''
Say 'To install it:'
Say '  1. Close Minecraft.'
Say '  2. Open your profile''s "mods" folder and DELETE the original rtx-remix-renderer jar (the one WITHOUT LightFix in its name).'
Say '  3. Copy the new ...-LightFix.jar (in the folder that just opened) into that mods folder.'
Say '     (If you have an older "translucent-light-fix-toggle" jar there, delete it too: the new jar contains it.)'
Say '  4. Start Minecraft. The first start is slower (it unpacks the runtime and builds shaders).'
Say 'In game: RTX Remix settings > "Light Transform Modifications".'
Say 'Afterwards you can delete the helper folder (RemixGlassFix-files or "work") to free about 3 GB.'
Say '=============================================================='
Start-Process explorer.exe $out
