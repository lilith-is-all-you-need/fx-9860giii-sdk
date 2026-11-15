# External G1A smoke tests

On 2026-11-15, two unchanged G1A files were loaded directly into the released Fx Studio 0.2.0 emulator. GDB started execution without an ELF; the control interface delivered keys and captured the actual 128×64 framebuffer. Each run used an isolated temporary directory. The original game files are not distributed by this repository.

| File | Header version | Observed result |
| --- | --- | --- |
| Wolfenst.g1a (98,708 bytes) | 01.20.0000 | Main menu and difficulty selection, 3D gameplay, movement, turning and shooting. Ammo decreased from 20 to 19. |
| Fruitnin.g1a (66,236 bytes) | 02.04.0001 | Animated title, menus, gameplay and fruit generation. In Peacefull mode, keyboard swipes produced visible cutting trails and increased the score from 0 to 12. |

Both observed runs completed without emulator-reported CPU/syscall errors. They establish basic interactive operation, not complete compatibility across levels, modes, saving, timing or physical hardware. No physical calculator was tested. Source-level debugging of these games was not tested because matching debug symbols were not supplied.

SHA-256 identities:

```text
a222ff7814aa3bbaebd9dd05cab37873f59dada6a882b0816c6669699725881a  FxEmulator.exe
d8c8b567b7a2f108e4969ca0f3461a9e82d9669c834f26f7f476f1b5eebf88ca  Wolfenst.g1a
5c5bd8f2c42add4feb9eb4112f134d00c45066eb80be805c3f872b27f451eaf6  Fruitnin.g1a
```

Game authors retain their respective rights. This result does not imply that the binaries are compatible with every calculator OS or that Fx Studio contains the games.
