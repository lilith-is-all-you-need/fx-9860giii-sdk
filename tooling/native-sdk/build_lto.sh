#!/usr/bin/env bash
set -euo pipefail
work="$1"
export PATH="/mingw64/bin:/usr/bin:/c/Program Files/Git/usr/bin" LANG=C.UTF-8 LC_ALL=C.UTF-8 TMPDIR="$work/tmp"
mkdir -p "$work/build-lto"
cd "$work/build-lto"
if [[ ! -f Makefile ]]; then
    "$work/source/gcc-14.1.0/lto-plugin/configure" \
        --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 --target=sh3eb-elf \
        --prefix="$work/prefix" --enable-shared --disable-static \
        --with-libiberty="$work/build-gcc/libiberty" \
        CC=gcc CFLAGS=-O2 LDFLAGS=-static-libgcc > "$work/lto-shared-configure.log" 2>&1
fi
make -j4 liblto_plugin.la > "$work/lto-shared-build.log" 2>&1
# The standalone configure is outside GCC's expected sibling layout; avoid its
# all-local libtool copy into ../gcc and install the real DLL directly.
mkdir -p "$work/prefix/libexec/gcc/sh3eb-elf/14.1.0"
cp .libs/liblto_plugin.dll "$work/prefix/libexec/gcc/sh3eb-elf/14.1.0/liblto_plugin.dll"
echo LTO_SHARED_READY
