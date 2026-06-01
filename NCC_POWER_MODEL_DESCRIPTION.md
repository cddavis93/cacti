# NCC Power Simulation in CACTI: Detailed Description

## Overview

This document describes how the NCC (Near-Cache Compute) hardware model was added to CACTI 7.0 and explains precisely what each computed quantity represents in terms of physical power dissipation.

CACTI is a circuit-level analytical model originally designed to characterize SRAM arrays (caches). The NCC units are combinational FP32 FMA circuits — not memory arrays — so a new module was written that borrows CACTI's existing technology-parameter infrastructure to estimate the power and area of the FP32 datapaths without requiring a full transistor-level netlist.

---

## What the NCC Hardware Is

Each NCC unit sits outside one L2 cache bank, between the sense amplifiers and the cache's output drivers. It contains **32 FP32 FMA datapaths** — one per warp thread — so that a full 32-thread warp can execute one NCC instruction (ncc_ffma, ncc_fmul, or ncc_fadd) in one cycle without issuing any memory traffic to the SM or the interconnect.

On the NVIDIA A100:
- 80 L2 cache slices × 32 FP32 FMAs per slice = **2,560 total NCC FP32 units**
- All 80 NCC units share the same clock domain as the L2 cache: **1,410 MHz**
- NCC units are only active when an NCC-marked instruction reaches the L2; otherwise they are idle (clock-gated)

---

## The Gate-Count Power Model

### Why Not Use CACTI's SRAM Model Directly

CACTI's existing power models are built around SRAM bitcell arrays: charge/discharge of bitlines, sense amplifier operation, decoder fanout, and H-tree interconnect. These are not applicable to FP32 arithmetic circuits. Instead, the NCC model uses CACTI's **device-level parameters** (`g_tp`) — which describe transistor behavior at the chosen technology node — and combines them with a **gate-count abstraction** of the FP32 FMA circuit.

### Gate-Count Abstraction

An FP32 FMA unit is modeled as **3,000 NAND2-equivalent gates**. This figure is drawn from published standard-cell FP32 multiplier and adder studies and is consistent with GPU die-area analysis at 7nm. A NAND2 gate is the canonical unit of digital logic complexity:

- It contains **4 transistors** (2 NMOS in series, 2 PMOS in parallel)
- Its drive strength, capacitance, and leakage scale predictably with gate width
- More complex gates (full adders, MUX cells) can be expressed in equivalent NAND2 counts

The total transistor count implied by the model is:

```
total_transistors = FMA_GATE_COUNT × TXN_PER_GATE × fus_per_unit × num_units
                  = 3000 × 4 × 32 × 80
                  = 30,720,000 transistors (~30.7M)
```

This is a reasonable fraction of A100's ~54B total transistors, considering the NCC units represent ~19% of one class of execution unit (FP32 FMAs).

---

## Area Model

### Formula

```
area_per_gate  = REF_AREA_GATE_MM2 × (F_sz_um / REF_F_SZ_UM)²
area_per_fma   = FMA_GATE_COUNT × area_per_gate
area_per_unit  = area_per_fma × fus_per_unit
total_area     = area_per_unit × num_units
```

### Calibration anchor (7nm)

The reference point is **TSMC N7** (the node used by the NVIDIA A100):
- A NAND2 standard cell occupies approximately **0.040 µm²** in the standard-cell library
- With a **2× routing overhead** (metal layers for power rails, signal routing, and fill): **~0.080 µm² = 8×10⁻⁸ mm²** per gate
- This is `REF_AREA_GATE_MM2 = 8e-8 mm²`

### Technology scaling

Standard-cell area scales approximately as **F²** (the square of the minimum feature size), because both the gate length and the contacted poly pitch shrink together. CACTI's `g_ip->F_sz_um` holds the user-specified feature size, so:

```
area_scale = (F_sz_um / 0.007)²
```

At 7nm: scale = 1.0 → area_per_unit = 32 × 3000 × 8e-8 mm² = **7.68×10⁻³ mm²** per unit, **0.614 mm² total** across 80 units (~1.5% of the estimated 40 mm² A100 L2 area).

At 90nm (current `cache.cfg` default): scale = (0.09/0.007)² ≈ 165 → the area grows proportionally. The 90nm numbers are physically correct for that node but are not the target configuration — change `-technology (u)` to `0.007` for A100-representative results.

---

## Dynamic Power Model

### What Dynamic Power Represents

Dynamic (switching) power is the energy dissipated every time a logic gate changes state — a CMOS gate charges or discharges its output node capacitance, moving charge through the supply rail. It is the dominant power component when circuits are active.

### Formula

```
C_per_gate = gate_C(min_w_nmos_, 0) × TXN_PER_GATE
C_per_fma  = C_per_gate × FMA_GATE_COUNT
C_per_unit = C_per_fma × fus_per_unit
P_dyn      = α × C_per_unit × Vdd² × f
```

### CACTI's `gate_C()` Function

`gate_C(width, wirelength)` (`basic_circuit.cc:99`) returns the **total gate input capacitance** of a transistor with the given gate width, in Farads. It computes:

```
C_gate = (C_g_ideal + C_overlap + 3×C_fringe) × width + l_phy × C_polywire
```

Where all parameters come from `g_tp.peri_global` (the peripheral global device type — the transistor flavor used in logic outside the SRAM bitcell). `C_g_ideal` is the intrinsic oxide capacitance per unit width (F/µm), `C_overlap` and `C_fringe` are parasitic fringing terms, and `l_phy × C_polywire` is the polysilicon interconnect contribution.

The model uses `g_tp.min_w_nmos_` — the minimum manufacturable NMOS gate width at the current technology node — as the transistor width. This gives a **conservative lower-bound capacitance** (wider transistors drive more load and switch more charge). Multiplying by `TXN_PER_GATE = 4` accounts for all four transistors in each equivalent NAND2.

### Activity Factor (α)

The activity factor `α = 0.054` (5.4%) is the measured **FU utilization** for NCC_FMUL and NCC_FADD instructions from the dissertation's characterization of LGCN and GIN workloads. It represents the fraction of clock cycles in which an NCC FP32 FMA actually switches — i.e., executes an instruction and charges/discharges its output capacitance. The remaining 94.6% of cycles, NCC units are idle and consume only leakage.

For NCC_FFMA (3-operand), the utilization is 3.6%, so `ncc_activity_factor` can be lowered to `0.036` for an FFMA-weighted workload.

### Supply Voltage (`Vdd`)

`g_tp.peri_global.Vdd` is the supply voltage for peripheral logic at the chosen technology node, loaded from CACTI's `tech_params/*.dat` files. At 90nm it is typically ~1.0–1.2V; at scaled nodes it decreases, sharply reducing `Vdd²` and thus dynamic power.

---

## Leakage Power Model

### What Leakage Represents

Leakage (subthreshold) power is the energy dissipated by transistors even when they are not switching. In nanometer-scale CMOS, some current always flows from drain to source when a transistor is nominally "off," because the supply voltage is comparable to the threshold voltage. Leakage is independent of workload activity and is present whenever the chip is powered.

### Formula

```
I_leak_per_gate = cmos_Isub_leakage(min_n, min_p, fanin=2, gate_type=nand)
P_leak_per_unit = I_leak_per_gate × FMA_GATE_COUNT × fus_per_unit × Vdd
P_leak_total    = P_leak_per_unit × num_units
```

### CACTI's `cmos_Isub_leakage()` Function

`cmos_Isub_leakage(nWidth, pWidth, fanin, gate_type)` (`basic_circuit.cc:607`) computes the **average subthreshold leakage current** for a CMOS gate, accounting for:

1. **Individual transistor leakage**: calls `simplified_nmos_leakage(width)` and `simplified_pmos_leakage(width)`, which use `g_tp.peri_global.I_off_n` and `I_off_p` (off-state leakage current per unit width, A/µm)
2. **Stack effect**: transistors in series (as in a 2-input NAND) leak less than a single transistor because the intermediate node floats to a voltage that reverse-biases the lower transistor. The function models this with `UNI_LEAK_STACK_FACTOR` per stacking level.
3. **Input state averaging**: not all input combinations are equally likely; the function averages leakage over all 2^fanin input states, weighted uniformly.

The call uses:
- `min_n = g_tp.min_w_nmos_` — NMOS width
- `min_p = g_tp.peri_global.n_to_p_eff_curr_drv_ratio × min_w_nmos_` — PMOS width sized to match NMOS drive current (standard practice in cell design)
- `fanin = 2` — NAND2 has 2 inputs
- `gate_type = nand` — selects the NAND topology (NMOS stack in series, PMOS in parallel)

The returned current is then multiplied by the gate count, the number of FMAs per unit, and `Vdd` to get power in Watts.

---

## How the Two Power Components Relate

The dynamic and leakage models use **orthogonal data paths** from `g_tp`:

| Quantity | Source in `g_tp` | Physical meaning |
|----------|-----------------|-----------------|
| `C_g_ideal` (via `gate_C()`) | `peri_global.C_g_ideal` | Oxide capacitance per µm gate width |
| `C_overlap`, `C_fringe` (via `gate_C()`) | `peri_global.*` | Parasitic gate edge capacitances |
| `Vdd` | `peri_global.Vdd` | Supply voltage |
| `I_off_n`, `I_off_p` (via `cmos_Isub_leakage()`) | `peri_global.I_off_n/p` | Off-state drain current per µm width |
| `n_to_p_eff_curr_drv_ratio` | `peri_global.*` | PMOS/NMOS width ratio for current matching |

All of these are populated by `technology.cc`'s `init_tech_params()` function, which reads CACTI's binary `tech_params/*.dat` files and interpolates between measured ITRS data points for the requested technology node. This is the same parameter set used by every other model in CACTI (wire models, sense amplifiers, decoders), so the NCC model is **automatically consistent** with the rest of CACTI's technology assumptions.

---

## Integration with CACTI's Execution Flow

```
./cacti -infile cache.cfg
  │
  ├─ InputParameter::parse_cfg()         ← reads -ncc_* keys into g_ip
  ├─ init_tech_params(g_ip->F_sz_um)     ← populates g_tp from tech_params/*.dat
  ├─ solve(&fin_res)                     ← CACTI's normal UCA/NUCA search
  ├─ output_UCA(&fin_res)                ← prints cache timing, power, area
  │
  └─ if (g_ip->ncc_enable):
       model_ncc(NCC_params)             ← ncc.cc: area + dynamic + leakage
       output_NCC(NCC_result, *g_ip)     ← prints NCC block to stdout
```

The NCC model runs **after** the cache solve, not inside it. It does not affect the cache optimization loop, MSHR sizing, bank counts, or any other UCA parameter. It is a standalone estimation appended to the output. `g_tp` is already initialized by the time `model_ncc()` is called, so all device parameters reflect the correct technology node.

---

## Interpreting the Output

```
===== NCC (Near-Cache Compute) Results =====
  Units:               80
  FP32 FMAs / unit:    32
  Technology:          90 nm        ← change to 7 nm for A100-representative results
  Clock:               1410 MHz
  Activity factor:     0.054

  Area per NCC unit:   X.XX mm^2   ← physical silicon area of 32 FP32 FMAs + routing
  Total NCC area:      X.XX mm^2   ← across all 80 L2 slices

  Dynamic power/unit:  X.XX mW     ← switching power when NCC instructions execute
  Total dynamic power: X.XX W      ← 80 units × dynamic_per_unit

  Leakage power/unit:  X.XX mW     ← always-on subthreshold current × Vdd
  Total leakage power: X.XX W      ← 80 units × leakage_per_unit
============================================
```

**Total NCC power budget** = Total dynamic + Total leakage. Since α = 0.054, leakage typically exceeds dynamic power — the NCC units spend most of their time idle, waiting for patterns to appear.

To compare against the L2 cache itself: CACTI's UCA output reports the cache's leakage and dynamic power in the lines above the NCC block. The ratio of NCC total power to L2 total power is a direct measure of how much overhead the NCC units add to the memory subsystem.

---

## Sensitivity and Limitations

**Sensitive parameters:**
- `-technology (u)`: area scales as F², power scales as Vdd² and I_off per technology node
- `-ncc_activity_factor`: linearly scales dynamic power; 0.036 for ncc_ffma, 0.054 for ncc_fmul/ncc_fadd
- `FMA_GATE_COUNT` (hardcoded in `ncc.cc`): the single largest source of modeling uncertainty; plausible range 2000–4000 from literature

**Known limitations:**
- The model assumes uniform minimum-width transistors throughout the FMA; real designs use wider transistors for critical paths, which increases both capacitance and leakage
- Wire/interconnect power within the FMA datapath is not modeled (would add 20–50% to dynamic power in practice)
- The 7nm area calibration extrapolates below CACTI's supported minimum (16nm); accuracy at 7nm depends on how well F² scaling holds at that node
- Clock tree power to the NCC units is not included (typically 20–30% of logic dynamic power)

These limitations are consistent with the tool's academic purpose: providing order-of-magnitude area and power estimates for architectural design-space exploration, not tape-out-accurate characterization.
