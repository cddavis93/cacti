"""
compute_power.py
----------------
Combines CACTI energy-per-access values with accel-sim L2 access counts
to produce workload-level L2 + NCC power estimates.

CACTI values are read from a CACTI .out file (default: cache_a100_baseline.cfg.out).
Config files live in cacti/configs/; .out files are written to cacti/ root by CACTI.
The script selects the last row in the .out file whose capacity, associativity,
and output-width match the A100 slice config (524288 B, 16-way, 1024-bit).

Usage:
  python3 compute_power.py [path/to/cacti_run.out]

Sim source: sim_run_12.8/dissertation_sims/stats/converted/
"""

import csv
import sys
from pathlib import Path
from io import StringIO

# ---------------------------------------------------------------------------
# Config-matching criteria
# ---------------------------------------------------------------------------
# L2: 512 KB per slice, 16-way, 1024-bit output
L2_MATCH_CAPACITY_B = 524288
L2_MATCH_ASSOC      = 16
L2_MATCH_OUTPUT_W   = 1024

# L1: 128 KB per SM, 4-way, 1024-bit output
L1_MATCH_CAPACITY_B = 131072
L1_MATCH_ASSOC      = 4
L1_MATCH_OUTPUT_W   = 1024

# ---------------------------------------------------------------------------
# Fixed constants not present in the .out file
# ---------------------------------------------------------------------------
N_L2_SLICES = 80    # A100 L2 slices
N_L1_SMS    = 108   # A100 SMs (one L1 per SM)
CLOCK_HZ    = 1.41e9

# NCC hardware — from CACTI NCC model stdout (ncc.cc); not in .out file.
NCC_DYN_W          = 0.0282766   # W    NCC dynamic power  (80 units, alpha=0.054)
NCC_LEAK_W         = 0.157266    # W    NCC leakage power  (80 units)
NCC_UNIT_AREA_MM2  = 0.0758596   # mm²  NCC area per unit  (32 FMAs @ 22nm)
NCC_TOTAL_AREA_MM2 = 6.06877     # mm²  NCC area total     (80 units)

# ---------------------------------------------------------------------------
# Load CACTI .out files
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).parent
CACTI_DIR   = SCRIPT_DIR.parent
CONFIGS_DIR = CACTI_DIR / "configs"
OUT_FILE    = Path(sys.argv[1]) if len(sys.argv) > 1 \
              else CONFIGS_DIR / "cache_a100_baseline.cfg.out"
L1_OUT_FILE = CONFIGS_DIR / "cache_a100_l1.cfg.out"

def load_cacti_out(path, cap_b, assoc, outw):
    """Return the last row in a CACTI .out file matching the given geometry."""
    match = None
    with open(path) as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            try:
                c = int(float(row["Capacity (bytes)"]))
                a = int(float(row["Associativity"]))
                w = int(float(row["Output width (bits)"]))
            except (KeyError, ValueError):
                continue
            if c == cap_b and a == assoc and w == outw:
                match = row
    if match is None:
        raise RuntimeError(
            f"No row in {path} matches capacity={cap_b}B assoc={assoc} outwidth={outw}b."
        )
    return match

# L2 values
l2 = load_cacti_out(OUT_FILE, L2_MATCH_CAPACITY_B, L2_MATCH_ASSOC, L2_MATCH_OUTPUT_W)
E_READ_NJ        = float(l2["Dynamic read energy (nJ)"])
E_WRITE_NJ       = float(l2["Dynamic write energy (nJ)"])
LEAK_PER_SLICE_W = float(l2["Standby leakage per bank(mW)"]) * 1e-3
TECH_NM          = float(l2["Tech node (nm)"])
ACCESS_TIME_NS   = float(l2["Access time (ns)"])
L2_AREA_MM2      = float(l2["Area (mm2)"])
LEAK_L2_TOTAL_W  = LEAK_PER_SLICE_W * N_L2_SLICES

# L1 values
l1 = load_cacti_out(L1_OUT_FILE, L1_MATCH_CAPACITY_B, L1_MATCH_ASSOC, L1_MATCH_OUTPUT_W)
L1_E_READ_NJ     = float(l1["Dynamic read energy (nJ)"])
L1_E_WRITE_NJ    = float(l1["Dynamic write energy (nJ)"])
L1_LEAK_PER_SM_W = float(l1["Standby leakage per bank(mW)"]) * 1e-3
L1_AREA_MM2      = float(l1["Area (mm2)"])
LEAK_L1_TOTAL_W  = L1_LEAK_PER_SM_W * N_L1_SMS

# Keep legacy alias for header display
LEAK_TOTAL_W = LEAK_L2_TOTAL_W
AREA_MM2     = L2_AREA_MM2

# ---------------------------------------------------------------------------
STATS_DIR = Path("/home/cory/accel-sim-framework/sim_run_12.8/"
                 "dissertation_sims/stats/converted")

WORKLOADS = [
    ("egnn",  "cora"),
    ("egnn",  "kinship"),
    ("gin",   "IMDBMULTI"),
    ("gin",   "MUTAG"),
    ("lgcn",  "gowalla"),
    ("lgcn",  "yelp2018"),
    ("igb",   "gcn_tiny"),
    ("igb",   "sage_tiny"),
    ("igb",   "gat_tiny"),
]

# ---------------------------------------------------------------------------
def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))

def workload_power(rows):
    total_cycles  = 0.0
    l2_reads = l2_writes = 0.0
    l1_reads = l1_writes = 0.0
    for row in rows:
        total_cycles += safe_float(row["gpu_tot_sim_cycle"])
        l2_reads     += safe_float(row["L2_read_total_access"])
        l2_writes    += safe_float(row["L2_write_total_access"])
        l1_reads     += safe_float(row["L1_read_total_access"])
        l1_writes    += safe_float(row["L1_write_total_access"])

    time_s = total_cycles / CLOCK_HZ

    l2_energy_J = (l2_reads * E_READ_NJ    + l2_writes * E_WRITE_NJ)    * 1e-9
    l1_energy_J = (l1_reads * L1_E_READ_NJ + l1_writes * L1_E_WRITE_NJ) * 1e-9

    l2_dyn_W = l2_energy_J / time_s if time_s > 0 else 0.0
    l1_dyn_W = l1_energy_J / time_s if time_s > 0 else 0.0

    return {
        "total_cycles": total_cycles,
        "l2_reads":     l2_reads,
        "l2_writes":    l2_writes,
        "l1_reads":     l1_reads,
        "l1_writes":    l1_writes,
        "l2_dyn_W":     l2_dyn_W,
        "l1_dyn_W":     l1_dyn_W,
        "l2_leak_W":    LEAK_L2_TOTAL_W,
        "l1_leak_W":    LEAK_L1_TOTAL_W,
        "total_W":      l2_dyn_W + l1_dyn_W + LEAK_L2_TOTAL_W + LEAK_L1_TOTAL_W,
    }

# ---------------------------------------------------------------------------
# Collect results
# ---------------------------------------------------------------------------
results = []
# optional CLI workload filter, e.g. `compute_power.py igb` or `... igb_gat_tiny`
_wf = [a for a in sys.argv[1:] if not Path(a).exists()]
_selected = [wd for wd in WORKLOADS
             if not _wf or wd[0] in _wf or f"{wd[0]}_{wd[1]}" in _wf]
for model, dataset in _selected:
    tag  = f"{model}_{dataset}"
    base = workload_power(load_csv(STATS_DIR / f"baseline_{tag}_converted.csv"))
    ncc  = workload_power(load_csv(STATS_DIR / f"ncc_fp3_{tag}_converted.csv"))

    base_full_W = base["total_W"]
    ncc_full_W  = ncc["total_W"] + NCC_DYN_W + NCC_LEAK_W

    # Mixed: baseline L2 activity + NCC L1 activity + NCC hardware units.
    # Time base = baseline cycles so L2 dynamic is unchanged from baseline.
    base_time_s     = base["total_cycles"] / CLOCK_HZ
    mix_l1_energy_J = (ncc["l1_reads"] * L1_E_READ_NJ + ncc["l1_writes"] * L1_E_WRITE_NJ) * 1e-9
    mix_l1_dyn_W    = mix_l1_energy_J / base_time_s if base_time_s > 0 else 0.0
    mix_l2_dyn_W    = base["l2_dyn_W"]   # baseline L2 accesses over baseline time
    mix_full_W      = mix_l1_dyn_W + mix_l2_dyn_W + LEAK_L1_TOTAL_W + LEAK_L2_TOTAL_W \
                      + NCC_DYN_W + NCC_LEAK_W

    results.append({
        "workload":              tag,
        # baseline
        "base_l2_reads":         base["l2_reads"],
        "base_l2_writes":        base["l2_writes"],
        "base_l1_reads":         base["l1_reads"],
        "base_l1_writes":        base["l1_writes"],
        "base_cycles":           base["total_cycles"],
        "base_l1_dyn_W":         base["l1_dyn_W"],
        "base_l2_dyn_W":         base["l2_dyn_W"],
        "base_l1_leak_W":        base["l1_leak_W"],
        "base_l2_leak_W":        base["l2_leak_W"],
        "base_full_total_W":     base_full_W,
        # ncc
        "ncc_l2_reads":          ncc["l2_reads"],
        "ncc_l2_writes":         ncc["l2_writes"],
        "ncc_l1_reads":          ncc["l1_reads"],
        "ncc_l1_writes":         ncc["l1_writes"],
        "ncc_cycles":            ncc["total_cycles"],
        "ncc_l1_dyn_W":          ncc["l1_dyn_W"],
        "ncc_l2_dyn_W":          ncc["l2_dyn_W"],
        "ncc_l1_leak_W":         ncc["l1_leak_W"],
        "ncc_l2_leak_W":         ncc["l2_leak_W"],
        "ncc_hw_dyn_W":          NCC_DYN_W,
        "ncc_hw_leak_W":         NCC_LEAK_W,
        "ncc_full_total_W":      ncc_full_W,
        # area
        "l1_sm_area_mm2":        L1_AREA_MM2,
        "l1_total_area_mm2":     L1_AREA_MM2 * N_L1_SMS,
        "l2_slice_area_mm2":     L2_AREA_MM2,
        "l2_total_area_mm2":     L2_AREA_MM2 * N_L2_SLICES,
        "ncc_unit_area_mm2":     NCC_UNIT_AREA_MM2,
        "ncc_total_area_mm2":    NCC_TOTAL_AREA_MM2,
        "system_total_area_mm2": L1_AREA_MM2 * N_L1_SMS + L2_AREA_MM2 * N_L2_SLICES + NCC_TOTAL_AREA_MM2,
        # mixed (baseline L2 + NCC L1 + NCC hardware)
        "mix_l1_reads":          ncc["l1_reads"],
        "mix_l1_writes":         ncc["l1_writes"],
        "mix_l2_reads":          base["l2_reads"],
        "mix_l2_writes":         base["l2_writes"],
        "mix_cycles":            base["total_cycles"],
        "mix_l1_dyn_W":          mix_l1_dyn_W,
        "mix_l2_dyn_W":          mix_l2_dyn_W,
        "mix_l1_leak_W":         LEAK_L1_TOTAL_W,
        "mix_l2_leak_W":         LEAK_L2_TOTAL_W,
        "mix_hw_dyn_W":          NCC_DYN_W,
        "mix_hw_leak_W":         NCC_LEAK_W,
        "mix_full_total_W":      mix_full_W,
        # deltas
        "delta_l1_dyn_W":        ncc["l1_dyn_W"] - base["l1_dyn_W"],
        "delta_l2_dyn_W":        ncc["l2_dyn_W"] - base["l2_dyn_W"],
        "delta_full_total_W":    ncc_full_W - base_full_W,
        "mix_delta_full_total_W": mix_full_W - base_full_W,
    })

# ---------------------------------------------------------------------------
# Render text output into a string so it can go to both stdout and file
# ---------------------------------------------------------------------------
buf = StringIO()

def emit(*args, **kwargs):
    print(*args, **kwargs)
    print(*args, **kwargs, file=buf)

W = 155
emit("=" * W)
emit(f"  Technology : {TECH_NM:.0f} nm    Clock: {CLOCK_HZ/1e9:.2f} GHz")
emit(f"  L2 .out    : {OUT_FILE}")
emit(f"    E_read={E_READ_NJ} nJ  E_write={E_WRITE_NJ} nJ  "
     f"Leak/slice={LEAK_PER_SLICE_W*1e3:.3f} mW  "
     f"({LEAK_L2_TOTAL_W:.3f} W x{N_L2_SLICES})  Area/slice={L2_AREA_MM2:.4f} mm²")
emit(f"  L1 .out    : {L1_OUT_FILE}")
emit(f"    E_read={L1_E_READ_NJ} nJ  E_write={L1_E_WRITE_NJ} nJ  "
     f"Leak/SM={L1_LEAK_PER_SM_W*1e3:.3f} mW  "
     f"({LEAK_L1_TOTAL_W:.3f} W x{N_L1_SMS})  Area/SM={L1_AREA_MM2:.4f} mm²")
emit("=" * W)

FMT = "{:<22} {:>8} {:>12} {:>12} {:>12} {:>12} {:>10} {:>10} {:>10} {:>10} {:>10} {:>10} {:>12}"
emit(FMT.format(
    "Workload", "Config",
    "L1 reads", "L1 writes", "L2 reads", "L2 writes",
    "L1 Dyn(W)", "L2 Dyn(W)", "L1 Lk(W)", "L2 Lk(W)",
    "NCC Dyn(W)", "NCC Lk(W)", "FULL TOT(W)"
))
emit("-" * W)

for r in results:
    emit(FMT.format(
        r["workload"], "baseline",
        f"{r['base_l1_reads']:.0f}", f"{r['base_l1_writes']:.0f}",
        f"{r['base_l2_reads']:.0f}", f"{r['base_l2_writes']:.0f}",
        f"{r['base_l1_dyn_W']:.4f}", f"{r['base_l2_dyn_W']:.4f}",
        f"{r['base_l1_leak_W']:.3f}", f"{r['base_l2_leak_W']:.3f}",
        "—", "—",
        f"{r['base_full_total_W']:.3f}"
    ))
    emit(FMT.format(
        "", "ncc_fp3",
        f"{r['ncc_l1_reads']:.0f}", f"{r['ncc_l1_writes']:.0f}",
        f"{r['ncc_l2_reads']:.0f}", f"{r['ncc_l2_writes']:.0f}",
        f"{r['ncc_l1_dyn_W']:.4f}", f"{r['ncc_l2_dyn_W']:.4f}",
        f"{r['ncc_l1_leak_W']:.3f}", f"{r['ncc_l2_leak_W']:.3f}",
        f"{r['ncc_hw_dyn_W']:.4f}", f"{r['ncc_hw_leak_W']:.4f}",
        f"{r['ncc_full_total_W']:.3f}"
    ))
    emit(FMT.format(
        "", "mixed",
        f"{r['mix_l1_reads']:.0f}", f"{r['mix_l1_writes']:.0f}",
        f"{r['mix_l2_reads']:.0f}", f"{r['mix_l2_writes']:.0f}",
        f"{r['mix_l1_dyn_W']:.4f}", f"{r['mix_l2_dyn_W']:.4f}",
        f"{r['mix_l1_leak_W']:.3f}", f"{r['mix_l2_leak_W']:.3f}",
        f"{r['mix_hw_dyn_W']:.4f}", f"{r['mix_hw_leak_W']:.4f}",
        f"{r['mix_full_total_W']:.3f}"
    ))
    emit(FMT.format(
        "", "delta",
        f"{r['ncc_l1_reads'] - r['base_l1_reads']:+.0f}",
        f"{r['ncc_l1_writes'] - r['base_l1_writes']:+.0f}",
        f"{r['ncc_l2_reads'] - r['base_l2_reads']:+.0f}",
        f"{r['ncc_l2_writes'] - r['base_l2_writes']:+.0f}",
        f"{r['delta_l1_dyn_W']:+.4f}", f"{r['delta_l2_dyn_W']:+.4f}",
        "0.000", "0.000", "—", "—",
        f"{r['delta_full_total_W']:+.3f}"
    ))
    emit(FMT.format(
        "", "mix_delta",
        f"{r['mix_l1_reads'] - r['base_l1_reads']:+.0f}",
        f"{r['mix_l1_writes'] - r['base_l1_writes']:+.0f}",
        "0", "0",
        f"{r['mix_l1_dyn_W'] - r['base_l1_dyn_W']:+.4f}", "0.0000",
        "0.000", "0.000",
        f"{r['mix_hw_dyn_W']:.4f}", f"{r['mix_hw_leak_W']:.4f}",
        f"{r['mix_delta_full_total_W']:+.3f}"
    ))
    emit()

emit("=" * W)
emit(f"  NCC hardware overhead (80 units x 32 FMAs, alpha=0.054) — from ncc.cc stdout:")
emit(f"    Dynamic : {NCC_DYN_W*1e3:.2f} mW    Leakage : {NCC_LEAK_W*1e3:.2f} mW    Total : {(NCC_DYN_W+NCC_LEAK_W)*1e3:.2f} mW")
emit(f"  L1 leakage (all 108 SMs, always-on): {LEAK_L1_TOTAL_W:.3f} W")
emit(f"  L2 leakage (all  80 slices, always-on): {LEAK_L2_TOTAL_W:.3f} W")
emit("=" * W)

# ---------------------------------------------------------------------------
# Save text file
# ---------------------------------------------------------------------------
TXT_OUT = SCRIPT_DIR / "power_results.txt"
TXT_OUT.write_text(buf.getvalue())
print(f"\n  Text output saved to: {TXT_OUT}")

# ---------------------------------------------------------------------------
# Save CSV
# ---------------------------------------------------------------------------
CSV_OUT = SCRIPT_DIR / "power_results.csv"
CSV_FIELDS = [
    "workload",
    # baseline power
    "base_l2_reads", "base_l2_writes", "base_l1_reads", "base_l1_writes", "base_cycles",
    "base_l1_dyn_W", "base_l2_dyn_W", "base_l1_leak_W", "base_l2_leak_W",
    "base_full_total_W",
    # ncc power
    "ncc_l2_reads", "ncc_l2_writes", "ncc_l1_reads", "ncc_l1_writes", "ncc_cycles",
    "ncc_l1_dyn_W", "ncc_l2_dyn_W", "ncc_l1_leak_W", "ncc_l2_leak_W",
    "ncc_hw_dyn_W", "ncc_hw_leak_W", "ncc_full_total_W",
    # mixed (baseline L2 + NCC L1 + NCC hardware)
    "mix_l1_reads", "mix_l1_writes", "mix_l2_reads", "mix_l2_writes", "mix_cycles",
    "mix_l1_dyn_W", "mix_l2_dyn_W", "mix_l1_leak_W", "mix_l2_leak_W",
    "mix_hw_dyn_W", "mix_hw_leak_W", "mix_full_total_W",
    # area
    "l1_sm_area_mm2", "l1_total_area_mm2",
    "l2_slice_area_mm2", "l2_total_area_mm2",
    "ncc_unit_area_mm2", "ncc_total_area_mm2", "system_total_area_mm2",
    # deltas
    "delta_l1_dyn_W", "delta_l2_dyn_W", "delta_full_total_W",
    "mix_delta_full_total_W",
]
with open(CSV_OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    w.writeheader()
    w.writerows(results)
print(f"  CSV  output saved to: {CSV_OUT}")
