#!/usr/bin/env bash
set -euo pipefail
work="$1"
export PATH="$work/prefix/bin:/mingw64/bin:/usr/bin:/c/Program Files/Git/usr/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8 TMPDIR="$work/tmp"
cp "$work/build-lto/liblto_plugin.la" "$work/build-gcc/gcc/liblto_plugin.la"
cp "$work/build-lto/.libs/liblto_plugin.dll" "$work/build-gcc/gcc/liblto_plugin.dll"
cd "$work/build-gcc/gcc"
cp auto-host.h auto-host-before-lto.h
bash ./config.status --recheck > "$work/gcc-lto-reconfigure.log" 2>&1
bash ./config.status >> "$work/gcc-lto-reconfigure.log" 2>&1
sed -i "s@$work/source/gcc-14.1.0@../../source/gcc-14.1.0@g" Makefile
grep 'HAVE_LTO_PLUGIN' auto-host.h
cd ..
make -j8 all-gcc MAKEINFO=true > "$work/gcc-lto-build.log" 2>&1
make install-gcc MAKEINFO=true > "$work/gcc-lto-install.log" 2>&1
bash "$work/build_lto.sh" "$work"
echo GCC_LTO_READY
