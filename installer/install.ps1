# Makes the patched RTX Remix for Minecraft jar. Started by Make-Patched-Mod.bat. Windows PowerShell 5.1 is enough.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root 'work'
$out  = if ($env:RGF_OUT) { $env:RGF_OUT } else { Join-Path $root 'output' }   # the single-file .bat sets RGF_OUT to its own folder

# Supported mod builds (NVIDIA's unmodified jars), identified ONLY by size and MD5, never by file name.
$mods = @(
    @{ Version = '0.1.1'; Size = 1035282184; Md5 = '0b9c4d5f272fc4627d48ba6c636f2ef5' },
    @{ Version = '0.1.0'; Size = 1034998399; Md5 = 'c4551ac851988aa6ec5b6299c8cbd259' }
)
# The folder this file was started from: the .bat's own folder (RGF_OUT for the single-file .bat, the extracted folder for the zip).
# The mod jar is looked for in THIS folder and nowhere else on the PC; nothing is downloaded for it.
$src = if ($env:RGF_OUT) { $env:RGF_OUT } else { $root }
# the single-file .bat passes its folder WITH a trailing backslash; before a closing quote that backslash would swallow the quote of the argument when the path contains spaces
$src = $src.TrimEnd([char]92); $out = $out.TrimEnd([char]92)
# The helper tools below (portable Python, SPIR-V tools) are downloaded: official sources, fixed versions, checksums.
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

# The original mod: only the jar(s) in the folder this file was started from, matched by size and MD5 (any file name).
# Returns every match, so a folder holding both a 0.1.0 and a 0.1.1 jar patches both. Jars with LightFix in the name (our own output) are skipped.
function Find-SideMods {
    $hits = @()
    foreach ($f in (Get-ChildItem -LiteralPath $src -Filter '*.jar' -File -ErrorAction SilentlyContinue)) {
        if ($f.Name -like '*LightFix*') { continue }
        foreach ($m in $mods) {
            if ($f.Length -eq $m.Size -and (Get-FileHash -Algorithm MD5 -Path $f.FullName).Hash.ToLower() -eq $m.Md5) {
                $hits += @{ Path = $f.FullName; Version = $m.Version }
            }
        }
    }
    return $hits
}

if (-not [Environment]::Is64BitOperatingSystem) { Fail 'This needs 64-bit Windows 10 or 11.' }
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Fail 'curl.exe was not found (it ships with Windows 10 version 1803 and newer).' }
if (-not (Test-Path (Join-Path $root 'prebuilt'))) { Fail 'The prebuilt folder is missing. Extract the whole zip first, do not run the .bat from inside the zip.' }

New-Item -ItemType Directory -Force -Path $work, $out | Out-Null
$free = (Get-PSDrive -Name ((Split-Path -Qualifier $root).TrimEnd(':'))).Free
if ($free -lt 4.5GB) { Fail ('About 4.5 GB of free disk space is needed here, only {0:N1} GB is free.' -f ($free / 1GB)) }

Say ''
Say '=== RTX Remix for Minecraft: glass and water light fix ==='
Say 'This patches NVIDIA''s original mod (0.1.0 or 0.1.1) and writes ONE jar next to this file, named ...-LightFix.jar. It only looks at the jar in the folder this file is in; the jar is recognised by its hash, not its name.'
Say ''

Say "Looking for NVIDIA's original mod jar in: $src"
$targets = @(Find-SideMods)
if ($targets.Count -eq 0) {
    $others = @(Get-ChildItem -LiteralPath $src -Filter '*.jar' -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike '*LightFix*' })
    Say ''
    if ($others.Count -gt 0) {
        Say 'These jar files are in the folder, but none matches a supported build:'
        foreach ($o in $others) { Say ('  {0}  ({1:N0} bytes)' -f $o.Name, $o.Length) }
        Fail 'None of them is NVIDIA''s original RTX Remix for Minecraft jar, version 0.1.0 or 0.1.1 (an already patched jar, a different version or a damaged download do not match).'
    }
    Fail ('No mod jar found next to this file. Put NVIDIA''s original rtx-remix-renderer jar (version 0.1.0 or 0.1.1, from https://github.com/NVIDIAGameWorks/rtx-remix-minecraft/releases) in the same folder as this file, then run this again. Looked in: ' + $src)
}
foreach ($t in $targets) { Say ('Found the original mod, version {0}: {1}' -f $t.Version, $t.Path) }
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

# 3. Patch each jar that was found (the version is taken from its hash by build_patched_jar.py)
foreach ($t in $targets) {
    Say ''
    Say ('Patching version {0} ...' -f $t.Version)
    & $py -I (Join-Path $PSScriptRoot 'build_patched_jar.py') --jar $t.Path --prebuilt (Join-Path $root 'prebuilt') --spirv-tools $spvDir --out $out --work $work
    if ($LASTEXITCODE -ne 0) { Fail 'the patch did not finish (see the messages above).' }
}

Say ''
Say '=============================================================='
Say 'All done. The patched mod is here:'
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
if (-not $env:RGF_NOOPEN) { Start-Process explorer.exe $out }   # RGF_NOOPEN=1 (automated runs) skips opening the folder
