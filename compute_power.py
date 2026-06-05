"""
compute_power.py
----------------
Combines CACTI energy-per-access values with accel-sim L2 access counts
to produce workload-level L2 + NCC power estimates.

CACTI values are read from a CACTI .out file (default: cache_a100_baseline.cfg.out).
The script selects the last row in the .out file whose capacity, associativity,
and output-width match the A100 slice config (524288 B, 16-way, 1024-bit).

Usage:
  python3 compute_power.py [path/to/cacti_run.out]

Sim source: sim_run_12.8/dissertation_sims/stats/converted/
"""

import csv
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Config-matching criteria — identifies the A100 L2 slice row in the .out file
# ---------------------------------------------------------------------------
MATCH_CAPACITY_B   = 524288   # 512 KB per slice
MATCH_ASSOC        = 16
MATCH_OUTPUT_W     = 1024     # bits (one 128-byte cache line)

# ---------------------------------------------------------------------------
# Fixed constants not present in the .out file
# ---------------------------------------------------------------------------
N_SLICES   = 80       # A100 L2 slices
CLOCK_HZ   = 1.41e9  # A100 L2 clock (Hz)

# NCC hardware additions — from CACTI NCC model stdout (ncc.cc output).
# Not written to the .out file; kept here as verified constants.
NCC_DYN_W  = 0.0282766   # W  NCC dynamic power  (80 units, alpha=0.054)
NCC_LEAK_W = 0.157266    # W  NCC leakage power  (80 units)

# ---------------------------------------------------------------------------
# Load CACTI .out file and extract E_read, E_write, leakage
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
OUT_FILE   = Path(sys.argv[1]) if len(sys.argv) > 1 \
             else SCRIPT_DIR / "cache_a100_baseline.cfg.out"

def load_cacti_out(path):
    """
    Parse a CACTI .out CSV and return the last row matching the A100 slice
    config.  Raises if no matching row is found.
    """
    match = None
    with open(path) as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            try:
                cap   = int(float(row["Capacity (bytes)"]))
                assoc = int(float(row["Associativity"]))
                outw  = int(float(row["Output width (bits)"]))
            except (KeyError, ValueError):
                continue
            if cap == MATCH_CAPACITY_B and assoc == MATCH_ASSOC and outw == MATCH_OUTPUT_W:
                match = row
    if match is None:
        raise RuntimeError(
            f"No row in {path} matches capacity={MATCH_CAPACITY_B}B "
            f"assoc={MATCH_ASSOC} outwidth={MATCH_OUTPUT_W}b.\n"
            f"Run: ./cacti -infile cache_a100_baseline.cfg"
        )
    return match

row = load_cacti_out(OUT_FILE)

E_READ_NJ       = float(row["Dynamic read energy (nJ)"])
E_WRITE_NJ      = float(row["Dynamic write energy (nJ)"])
# Standby leakage per bank already combines subthreshold + gate leakage
LEAK_PER_SLICE_W= float(row["Standby leakage per bank(mW)"]) * 1e-3
TECH_NM         = float(row["Tech node (nm)"])
ACCESS_TIME_NS  = float(row["Access time (ns)"])
AREA_MM2        = float(row["Area (mm2)"])

LEAK_TOTAL_W    = LEAK_PER_SLICE_W * N_SLICES

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
    total_cycles = total_reads = total_writes = 0.0
    for row in rows:
        total_cycles += safe_float(row["gpu_tot_sim_cycle"])
        total_reads  += safe_float(row["L2_read_total_access"])
        total_writes += safe_float(row["L2_write_total_access"])

    time_s = total_cycles / CLOCK_HZ
    energy_J = (total_reads * E_READ_NJ + total_writes * E_WRITE_NJ) * 1e-9
    dyn_W    = energy_J / time_s if time_s > 0 else 0.0

    return {
        "total_cycles": total_cycles,
        "total_reads":  total_reads,
        "total_writes": total_writes,
        "dyn_W":        dyn_W,
        "leak_W":       LEAK_TOTAL_W,
        "total_W":      dyn_W + LEAK_TOTAL_W,
    }

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
print("=" * 100)
print(f"  CACTI .out source : {OUT_FILE}")
print(f"  Technology        : {TECH_NM:.0f} nm    "
      f"Access time: {ACCESS_TIME_NS:.3f} ns    "
      f"Area/slice: {AREA_MM2:.4f} mm²  ({AREA_MM2*N_SLICES:.2f} mm² total)")
print(f"  E_read = {E_READ_NJ} nJ/access    "
      f"E_write = {E_WRITE_NJ} nJ/access    "
      f"Leakage/slice = {LEAK_PER_SLICE_W*1e3:.3f} mW  "
      f"({LEAK_TOTAL_W:.3f} W total)")
print(f"  Clock: {CLOCK_HZ/1e9:.2f} GHz    Slices: {N_SLICES}")
print("=" * 100)

FMT = "{:<22} {:>8} {:>12} {:>12} {:>10} {:>10} {:>10} {:>10} | {:>10} {:>10} {:>10}"
print(FMT.format(
    "Workload", "Config",
    "L2 reads", "L2 writes", "Cycles",
    "Dyn (W)", "Leak (W)", "Total (W)",
    "+NCC dyn", "+NCC lk", "NCC tot (W)"
))
print("-" * 100)

for model, dataset in WORKLOADS:
    tag = f"{model}_{dataset}"

    base = workload_power(load_csv(STATS_DIR / f"baseline_{tag}_converted.csv"))
    ncc  = workload_power(load_csv(STATS_DIR / f"ncc_fp3_{tag}_converted.csv"))
    ncc_total_W = ncc["total_W"] + NCC_DYN_W + NCC_LEAK_W

    print(FMT.format(
        tag, "baseline",
        f"{base['total_reads']:.0f}", f"{base['total_writes']:.0f}",
        f"{base['total_cycles']:.0f}",
        f"{base['dyn_W']:.4f}", f"{base['leak_W']:.3f}", f"{base['total_W']:.3f}",
        "", "", ""
    ))
    print(FMT.format(
        "", "ncc_fp3",
        f"{ncc['total_reads']:.0f}", f"{ncc['total_writes']:.0f}",
        f"{ncc['total_cycles']:.0f}",
        f"{ncc['dyn_W']:.4f}", f"{ncc['leak_W']:.3f}", f"{ncc['total_W']:.3f}",
        f"{NCC_DYN_W:.4f}", f"{NCC_LEAK_W:.4f}", f"{ncc_total_W:.3f}"
    ))

    delta_dyn = ncc["dyn_W"] - base["dyn_W"]
    delta_tot = ncc_total_W  - base["total_W"]
    print(FMT.format(
        "", "delta", "", "", "",
        f"{delta_dyn:+.4f}", "0.000", f"{delta_tot:+.3f}",
        "", "", ""
    ))
    print()

print("=" * 100)
print(f"  NCC hardware overhead (80 units x 32 FMAs, alpha=0.054) — not in .out file:")
print(f"    Dynamic : {NCC_DYN_W*1e3:.2f} mW")
print(f"    Leakage : {NCC_LEAK_W*1e3:.2f} mW")
print(f"    Total   : {(NCC_DYN_W+NCC_LEAK_W)*1e3:.2f} mW")
print("=" * 100)
