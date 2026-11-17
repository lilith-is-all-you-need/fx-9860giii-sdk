# Loader Suite 0.2 integration evidence

Date: 2026-11-18. No new physical-calculator acceptance is claimed.

| Area | Observed result | Limit |
| --- | --- | --- |
| Offline preparation | 38 loader/profile/session tests passed, including stale-result rejection, missing/edited profile, relocated results, old artifact manifests and dynamic page boundaries | Caller lifecycle test uses a host backend double |
| Large profile/library | 10 tests passed; headers, counts, capacity, flags, budgets, exact hook bytes and source snapshots checked | A declared source ABI does not prove all runtime paths |
| Flash calculator builds | Debug and Release produced; original 22 directory/legacy/edge checks passed, final revision adds two metadata consistency checks | The validation file distinguishes build hashes; final image was not claimed to rerun every baseline |
| Extended execution | Final Giac directory with 699 pages/capacity 768 calculates 2+2=4; final original KhiCAS folder calculates 2+2=4 | Firmware-assisted HLE, not hardware |
| Independent source guest | Final Release crosses 2 MiB at 513 pages and releases allocations on return; prior same-mapper candidate also tests 2 and 730 pages, capacity 768 and zero spare entries | Empty-directory handling changed between candidate and final; records identify this |
| Ghidra | Actual Tetris and KhiCAS analysis; instruction bytes, exception ownership sites and immutable-input checks exported | Not all code/data boundaries or computed targets are recoverable |
| Profile Studio | Actual WinUI batches, dependencies-only and included launchers, independent export, reuse, language persistence, small-window layout, bundled offline Ghidra and cancellation passed | UI outputs remain test candidates |
| FxStudio | Published WPF app; actual knowledge window loads 4165 entries and search for 0x042C succeeds | Complete emulator/cycle fidelity is not asserted |

Final calculator artifacts:

| Filename | Bytes | SHA-256 |
| --- | ---: | --- |
| FlashLd.g1a | 19324 | `30478e2852179458820171ce1a2e4fea204daf2cc7e70b083fa7c4277fb71466` |
| KLoad.g1a | 16024 | `a184d966fb422cc9c07be82f6d7c4560857ff242394b1e301c3fd742cf2a5bb0` |
| ExtLoad.g1a | 12212 | `2a53cc82ecb628f30fc7500637b6dc78f743028aac778a1dbaff7440f11f944e` |

Detailed records: `probes/storage-loader/FOLDER-VALIDATION.json`,
`sdk/fxlarge/VALIDATION-DYNAMIC-20261118.json`,
`sdk/caller-session/VALIDATION.json`, `desktop/ProfileStudio/VALIDATION.json`.
The integration lock pins public component commits and normalized source hashes.
Private firmware, target G1As and raw machine traces are not published.

Still missing: arbitrary caller-stack/heap restoration and guest MENU resumption
through a general resident return backend; automatic executable Hook generation
for unknown oversized binaries; universal SH3-era binary adaptation. These paths
are explicitly rejected or documented as unsupported rather than marked complete.

Fast mode trusts previous content verification at the first mapping lookup of
each launch. Physical addresses are freshly queried, but same-size changes
between launches can be missed. Later mapping changes within that run are checked.
This tradeoff is explicit and Full remains the default.
