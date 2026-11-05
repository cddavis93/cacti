# NCC CACTI Implementation Plan

## What Was Done

1. Created git branch `ncc` for all NCC-related changes.
2. Verified CACTI builds and runs with `./cacti -infile configs/cache_a100_ncc.cfg`.
3. Implemented a new NCC (Near-Cache Compute) hardware model in CACTI that estimates
   area, dynamic power, and leakage for the FP32 FMA datapaths placed at each L2 cache slice.

---

## NCC Architecture (from dissertation)

- **Placement:** One NCC unit per L2 cache slice, placed outside the cache bank after sense amplifiers.
- **A100 configuration:** 80 L2 slices × 32 FP32 FMAs per unit = 2,560 NCC FP32 units total (~19% of A100's 13,824 CUDA cores).
- **ISA extensions:** `ncc_ffma`, `ncc_fmul`, `ncc_fadd` — all backed by the same FMA hardware.
- **Target pattern:** LDG → FFMA/FMUL/FADD → STG (compiler-identified def-use chains).
- **L2 clock:** 1,410 MHz (same as A100 memory subsystem clock).
- **FU utilization:** ~5.4% for 2-operand NCC ops; ~3.6% for ncc_ffma (from dissertation analysis).

---

## CACTI NCC Model Design

### Approach
FP32 FMA units are combinational logic — CACTI has no built-in model.
We use a **gate-count** reference calibrated at 7nm and scale with CACTI's technology parameters.

- **Gate count:** ~3,000 NAND2-equivalent gates per FP32 FMA (from published GPU die analysis).
- **Area:** scales as F² from 7nm anchor (8e-8 mm²/gate at 7nm, including routing overhead).
- **Dynamic power:** `α × C_eff × Vdd² × f`, where `C_eff` uses CACTI's `gate_C()` and `g_tp.peri_global.Vdd`.
- **Leakage:** uses CACTI's `cmos_Isub_leakage()` for a minimum-width NAND2, scaled by gate count.

### Reference calibration (7nm anchor)
- Feature size: 0.007 µm
- NAND2 cell area at TSMC N7: ~0.040 µm² physical + 2× routing = ~0.080 µm² = 8e-8 mm²/gate
- A100 sanity check at 7nm: 80 units × 32 FMAs × 3000 gates × 8e-8 = ~0.61 mm² total NCC area
  (≈ 1.5% of the ~40 mm² L2 cache area — physically plausible)

---

## Files Changed

| File | Change |
|------|--------|
| `ncc.h` | New: `NCC_params`, `NCC_result` structs; `model_ncc()` declaration |
| `ncc.cc` | New: FP32 FMA area/power model using `g_tp` technology parameters |
| `cacti_interface.h` | Added 5 NCC fields to `InputParameter` |
| `io.cc` | NCC defaults in constructor, config parsing, `output_NCC()` function, call after `output_UCA()` |
| `cacti.mk` | Added `ncc.cc` to `SRCS` |
| `configs/cache_a100_ncc.cfg` | Added NCC parameter section (A100 defaults: 80 units, 32 FMAs, 1410 MHz, α=0.054) |

---

## Config Parameters

```
-ncc_enable "true"          # enable NCC output block
-ncc_num_units 80           # one per L2 slice (A100 = 80)
-ncc_fus_per_unit 32        # FP32 FMAs per unit = warp width
-ncc_clock_mhz 1410         # NCC/L2 clock frequency (MHz)
-ncc_activity_factor 0.054  # FU switching activity (from dissertation)
```

To disable NCC output: set `-ncc_enable "false"` or omit the `-ncc_*` lines.

---

## Build & Run

```bash
make                          # debug build
./cacti -infile configs/cache_a100_ncc.cfg     # produces NCC section after UCA results
make opt                      # optimized (multi-threaded) build
```

---

## Technology Scaling

The model is parameterized by `g_ip->F_sz_um` (set via `-technology (u) X` in the config).
Change the technology node in `configs/cache_a100_ncc.cfg` to get correctly scaled NCC estimates:

| Technology | `-technology (u)` |
|-----------|-------------------|
| 90 nm     | 0.090             |
| 45 nm     | 0.045             |
| 32 nm     | 0.032             |
| 22 nm     | 0.022             |
| 16 nm     | 0.016             |
| 7 nm (A100) | 0.007 (extrapolated below CACTI's 16nm minimum) |
