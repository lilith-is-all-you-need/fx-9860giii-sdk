#!/usr/bin/env bash
set -euo pipefail
work="$1"
export PATH=/mingw64/bin:/usr/bin
export TMPDIR="$work/tmp"
flags='-O2 -ffunction-sections -fdata-sections -DGMP_STATICLIB -DXML_STATIC -DNEED_EXTERN_PC -DNCURSES_STATIC'
make -C "$work/build/bfd" bfdio.lo libbfd.la \
    -W "$work/source/gdb-16.3/bfd/bfdio.c" > "$work/static-bfd.log" 2>&1
# Static termcap owns PC; readline must only declare it. GDB must not use
# dllimport declarations from the installed ncurses-compatible headers.
make -C "$work/build/readline/readline" terminal.o libreadline.a \
    -W "$work/source/gdb-16.3/readline/readline/terminal.c" CFLAGS="$flags" \
    > "$work/static-terminal.log" 2>&1
cd "$work/build/gdb"
make utils.o -W "$work/source/gdb-16.3/gdb/utils.c" CXXFLAGS="$flags" \
    > "$work/static-utils.log" 2>&1
# Libtool's -static only covers libtool libraries; -all-static also prevents
# importing GMP/MPFR/zlib/winpthreads/termcap DLLs through ordinary -l options.
make gdb.exe -W gdb.o V=1 \
    LDFLAGS='-all-static -static-libgcc -static-libstdc++ -Wl,--gc-sections -Wl,--stack,12582912' \
    MAKEINFO=true > "$work/relink.log" 2>&1
make install MAKEINFO=true > "$work/reinstall.log" 2>&1
