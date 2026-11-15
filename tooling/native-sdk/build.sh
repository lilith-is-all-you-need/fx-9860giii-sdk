#!/usr/bin/env bash
set -euo pipefail
work="$1"
export PATH="$work/prefix/bin:/mingw64/bin:/usr/bin:/c/Program Files/Git/usr/bin"
export LANG=C.UTF-8 LC_ALL=C.UTF-8
export TMPDIR="$work/tmp"
mkdir -p "$TMPDIR" "$work/build-binutils" "$work/build-gcc" "$work/prefix"
export CC=gcc CXX=g++
export CPPFLAGS='-DGMP_STATICLIB'
export CFLAGS='-O2 -DGMP_STATICLIB'
export CXXFLAGS='-O2 -DGMP_STATICLIB'
export LDFLAGS='-static -static-libgcc -static-libstdc++'
cd "$work/build-binutils"
if [[ ! -f Makefile ]]; then
    "$work/source/binutils-2.42/configure" \
        --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 --target=sh3eb-elf \
        --prefix="$work/prefix" --program-prefix=sh-elf- \
        --disable-nls --disable-werror --disable-gdb --disable-gdbserver --disable-sim \
        --disable-gprofng --disable-gold --disable-shared --enable-static --without-zstd \
        MAKEINFO=true > "$work/binutils-configure.log" 2>&1
fi
make -j8 all-binutils all-gas all-ld MAKEINFO=true > "$work/binutils-build.log" 2>&1
make install-binutils install-gas install-ld MAKEINFO=true > "$work/binutils-install.log" 2>&1
echo 'BINUTILS_READY'
cd "$work/build-gcc"
if [[ ! -f Makefile ]]; then
    ../source/gcc-14.1.0/configure \
        --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 --target=sh3eb-elf \
        --prefix="$work/prefix" --program-prefix=sh-elf- \
        --with-multilib-list=m3,m4-nofpu --enable-languages=c,c++ --without-headers \
        --disable-bootstrap --disable-nls --disable-werror --disable-threads --disable-shared \
        --enable-static --enable-lto --enable-clocale=generic --disable-libstdcxx-verbose \
        --with-gmp=/mingw64 --with-mpfr=/mingw64 --with-mpc=/mingw64 --without-isl \
        MAKEINFO=true > "$work/gcc-configure.log" 2>&1
fi
make -j8 all-libiberty MAKEINFO=true > "$work/gcc-libiberty-build.log" 2>&1
bash "$work/build_lto.sh" "$work"
mkdir -p gcc
cp "$work/build-lto/liblto_plugin.la" gcc/liblto_plugin.la
cp "$work/build-lto/.libs/liblto_plugin.dll" gcc/liblto_plugin.dll
make -j8 configure-gcc MAKEINFO=true > "$work/gcc-configure-stage.log" 2>&1
# Native gengtype reads gtyp-input.list itself, so its contents cannot use MSYS
# /c/... spellings. Relative source paths work in both MSYS make and Win32 tools.
sed -i "s@$work/source/gcc-14.1.0@../../source/gcc-14.1.0@g" gcc/Makefile
make -j8 all-gcc MAKEINFO=true > "$work/gcc-build.log" 2>&1
make install-gcc MAKEINFO=true > "$work/gcc-install.log" 2>&1
bash "$work/build_lto.sh" "$work"
echo 'GCC_READY'
