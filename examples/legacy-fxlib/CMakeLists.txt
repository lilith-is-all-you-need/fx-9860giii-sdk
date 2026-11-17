cmake_minimum_required(VERSION 3.15)
project(FxStudioLegacy C)
include(GenerateG1A)
add_subdirectory(compat/fxlib)
add_executable(legacy_fxlib src/main.c compat/fxlib/fxlib_entry.c)
target_link_libraries(legacy_fxlib PRIVATE Fxlib::Compat)
# SHC-era programs often depend on signed plain char. Keep this explicit.
target_compile_options(legacy_fxlib PRIVATE -Wall -Wextra -fsigned-char)
generate_g1a(TARGET legacy_fxlib OUTPUT "LegacyFx.g1a" NAME "Legacy fxlib" INTERNAL "@FXLEG" ICON "assets/icon.png")
