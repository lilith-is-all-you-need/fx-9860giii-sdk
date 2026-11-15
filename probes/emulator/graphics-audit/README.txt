Fx Studio 0.1.1 graphics and asset pipeline audit

Run: python probes/emulator/graphics-audit/run.py
Run the already built ELF/G1A without rebuilding: append --reuse-build

This uses the actual portable 0.1.1 package's compiler, library, resource converter,
GDB and emulator. It is independent test source and does not modify that package.
It verifies the paired SuperH payload before running it. Generated image fixtures
are deterministic original test patterns from prepare_assets.py.

Covered: clipping, polygon fill, circle, ellipse, clipped line, transparent bopti
and subimage rendering, a bitmap digit font, gray engine startup/four shades and
return to mono. It is not complete gint API coverage or a physical-device test.

All seven mono pixel assertions passed (graphics_checks=127), gray initialization
returned zero, and all three stopped frames had no CPU error. The screenshot
samples show four distinct ordered gray levels; source/image goldens remain in
this directory. Results and GDB transcript are under results/.

Shutdown transport caveat: after detach then quit, this run observed a connection
reset while reading the final reply; the process still exited zero. The result
records this separately instead of calling it a graphics failure or claiming
that shutdown protocol passed.
