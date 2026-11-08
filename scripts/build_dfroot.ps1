# Rebuild DirtyFrag's libdfroot.so (an executable PIE) with the patched module.
#
# Needs the Android NDK. Tested with r27c.
#
#   $env:NDK = "C:\path\to\android-ndk-r27c"
#   .\build_dfroot.ps1 -Source C:\path\to\DirtyFrag\app\src\main\jni -OutDir .\build
#
# The source tree must contain:
#   ko/dfroot-android12-5.10.ko ... ko/dfroot-android17-6.18.ko
#   splicehelper.c, exp.c, libcxx.S, elf_parser.c
#
# Replace the android13-5.15 module with the patched one first.

param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$OutDir = ".\build",
    [string]$Target = "aarch64-linux-android33"
)

$ErrorActionPreference = "Stop"
if (-not $env:NDK) { throw "set `$env:NDK to the Android NDK root" }

$tc = Join-Path $env:NDK "toolchains\llvm\prebuilt\windows-x86_64"
$clang = Join-Path $tc "bin\clang.exe"
$strip = Join-Path $tc "bin\llvm-strip.exe"
$sysroot = Join-Path $tc "sysroot"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Push-Location $Source
try {
    # 1. splicehelper: freestanding static binary embedded via .incbin
    & $clang --target=$Target --sysroot=$sysroot splicehelper.c -o splicehelper `
        -nodefaultlibs -nostartfiles -ffreestanding -static
    if ($LASTEXITCODE) { throw "splicehelper build failed" }
    & $strip splicehelper

    # 2. objects
    foreach ($src in @("exp.c", "elf_parser.c", "libcxx.S")) {
        $obj = [IO.Path]::GetFileNameWithoutExtension($src) + ".o"
        & $clang --target=$Target --sysroot=$sysroot -I. -fno-stack-protector `
            -fomit-frame-pointer -Wall -Wextra -c $src -o $obj
        if ($LASTEXITCODE) { throw "$src build failed" }
    }

    # 3. link as PIE named libdfroot.so
    $out = Join-Path $OutDir "libdfroot.so"
    & $clang --target=$Target --sysroot=$sysroot exp.o elf_parser.o libcxx.o `
        -o $out -llog -pie "-Wl,-z,max-page-size=16384"
    if ($LASTEXITCODE) { throw "link failed" }
    Write-Host "built $out"
}
finally {
    Pop-Location
}
