#!/usr/bin/env bash
set -euo pipefail
work="$1"
export PATH=/mingw64/bin:/usr/bin
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export TMPDIR="$work/tmp"
mkdir -p "$TMPDIR" "$work/build" "$work/prefix"
export CC=gcc CXX=g++
export CPPFLAGS='-DGMP_STATICLIB -DXML_STATIC'
export CFLAGS='-O2 -ffunction-sections -fdata-sections -DGMP_STATICLIB -DXML_STATIC -DNEED_EXTERN_PC -DNCURSES_STATIC'
export CXXFLAGS='-O2 -ffunction-sections -fdata-sections -DGMP_STATICLIB -DXML_STATIC -DNEED_EXTERN_PC -DNCURSES_STATIC'
export LDFLAGS='-static -static-libgcc -static-libstdc++ -Wl,--gc-sections'
cd "$work/build"
if [[ ! -f Makefile ]]; then
    "$work/source/gdb-16.3/configure" \
        --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 --target=sh-elf \
        --prefix="$work/prefix" \
        --without-python --without-guile --without-debuginfod --without-babeltrace \
        --without-intel-pt --without-lzma --without-xxhash --without-curses \
        --with-gmp=/mingw64 --with-mpfr=/mingw64 --with-expat --with-libexpat-prefix=/mingw64 \
        --with-libiconv-prefix=/mingw64 --with-system-zlib --without-zstd \
        --disable-nls --disable-tui --disable-source-highlight --disable-threading \
        --disable-gdbserver --disable-sim --disable-gas --disable-binutils \
        --disable-ld --disable-gold --disable-gprof --disable-gprofng \
        --disable-werror --enable-static --disable-shared \
        MAKEINFO=true > "$work/configure.log" 2>&1
fi
make -j8 all-gdb MAKEINFO=true > "$work/build.log" 2>&1
make install-gdb MAKEINFO=true > "$work/install.log" 2>&1
printf 'Native GDB build completed\n'
