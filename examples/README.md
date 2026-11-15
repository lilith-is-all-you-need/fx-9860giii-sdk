# Fx Studio examples

Both examples run the compiled SuperH program in the preview. They use gint directly; no desktop replacement API is involved.

1. Open `counter-cpp` (C++17) or `counter-c` (C) in Fx Studio.
2. Choose **Debug**, build, and start. Execution first stops at `main`.
3. Continue. Press `+`, `−`, left, or right on the calculator keypad.
4. Put a breakpoint inside `change_counter`, continue, and press `+`.
5. Inspect `counter`, `previous`, `candidate`, the call stack, registers and memory. Step into `clamp_counter`.
6. `F1` resets the count; calculator `EXIT` returns from the add-in.

For a data watchpoint use `counter.value`. For a condition use `delta == 1`.

Use **Release** for the smaller installation artifact. Test on your own fx-9860GIII before relying on hardware compatibility. This workspace has not had a connected physical calculator for verification.
