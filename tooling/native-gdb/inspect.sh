#!/usr/bin/env bash
set -eu
export PATH=/mingw64/bin:/usr/bin
printf 'TOOLS\n'
command -v gcc g++ make bison flex makeinfo || true
printf 'PACKAGES\n'
pacman -Q mingw-w64-x86_64-gcc mingw-w64-x86_64-gmp mingw-w64-x86_64-mpfr mingw-w64-x86_64-zlib mingw-w64-x86_64-expat mingw-w64-x86_64-libiconv mingw-w64-x86_64-winpthreads 2>/dev/null
printf 'GDB\n'
/mingw64/bin/gdb-multiarch.exe -q -nx -batch -ex 'show configuration' -ex 'set architecture sh4' -ex 'show architecture'
