"""
compute_power.py
----------------
Combines CACTI energy-per-access values with accel-sim L2 access counts
to produce workload-level L2 + NCC power estimates.

CACTI source: cache_a100_baseline.cfg / cache.cfg (22nm, 512KB slice, 16-way, 128B line)
Sim source:   sim_run_12.8/dissertation_sims/stats/converted/
"""

import csv
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# CACTI-derived constants (from cache.cfg / cache_a100_baseline.cfg runs)
# ---------------------------------------------------------------------------
E_READ_NJ        = 0.786912   # nJ per L2 read access  (one slice)
E_WRITE_NJ       = 0.840105   # nJ per L2 write access (one slice)
LEAK_PER_SLICE_W = 158.671e-3 # W  subthreshold leakage per slice
GATE_PER_SLICE_W = 0.304706e-3# W  gate leakage per slice
N_SLICES         = 80         # A100 L2 slices

# Total leakage across all 80 slices (constant, independent of activity)
LEAK_TOTAL_W     = LEAK_PER_SLICE_W * N_SLICES
GATE_TOTAL_W     = GATE_PER_SLICE_W * N_SLICES

# NCC additions (from CACTI NCC model output, 80 units x 32 FMAs @ 22nm)
NCC_DYN_W        = 0.0282766  # W  NCC dynamic (alpha=0.054)
NCC_LEAK_W       = 0.157266   # W  NCC subthreshold leakage

# A100 L2 clock
CLOCK_HZ         = 1.41e9     # Hz

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

def safe_float(v):
    """Return float, treating 'NA' or empty as 0."""
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def load_csv(path):
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def workload_power(rows):
    """
    Aggregate L2 access counts and cycles across all kernels, then compute:
      - L2 dynamic power (W)
      - L2 leakage power (W)
    Returns dict of power components and supporting stats.
    """
    total_cycles = 0.0
    total_reads  = 0.0
    total_writes = 0.0

    for row in rows:
        cycles = safe_float(row["gpu_tot_sim_cycle"])
        reads  = safe_float(row["L2_read_total_access"])
        writes = safe_float(row["L2_write_total_access"])
        total_cycles += cycles
        total_reads  += reads
        total_writes += writes

    # Wall-clock time of the workload at A100 L2 clock
    time_s = total_cycles / CLOCK_HZ

    # Dynamic energy for all L2 accesses (nJ -> J)
    energy_read_J  = total_reads  * E_READ_NJ  * 1e-9
    energy_write_J = total_writes * E_WRITE_NJ * 1e-9
    total_energy_J = energy_read_J + energy_write_J

    # Average dynamic power over the workload
    dyn_W = total_energy_J / time_s if time_s > 0 else 0.0

    return {
        "total_cycles":  total_cycles,
        "total_reads":   total_reads,
        "total_writes":  total_writes,
        "time_us":       time_s * 1e6,
        "dyn_W":         dyn_W,
        "leak_W":        LEAK_TOTAL_W,
        "gate_W":        GATE_TOTAL_W,
        "total_W":       dyn_W + LEAK_TOTAL_W + GATE_TOTAL_W,
    }

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
print("=" * 100)
print(f"  L2 Cache Power  |  CACTI @ 22nm, 512KB/slice, 16-way, 128B line, A100 clock {CLOCK_HZ/1e9:.2f} GHz")
print(f"  Leakage (all 80 slices): {LEAK_TOTAL_W:.3f} W sub-threshold + {GATE_TOTAL_W*1e3:.3f} mW gate")
print(f"  E_read = {E_READ_NJ} nJ/access   E_write = {E_WRITE_NJ} nJ/access")
print("=" * 100)

# Column widths
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

    base_file = STATS_DIR / f"baseline_{tag}_converted.csv"
    ncc_file  = STATS_DIR / f"ncc_fp3_{tag}_converted.csv"

    base = workload_power(load_csv(base_file))
    ncc  = workload_power(load_csv(ncc_file))

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

    delta_dyn  = ncc["dyn_W"]  - base["dyn_W"]
    delta_tot  = ncc_total_W   - base["total_W"]
    print(FMT.format(
        "", "delta",
        "", "", "",
        f"{delta_dyn:+.4f}", "0.000", f"{delta_tot:+.3f}",
        "", "", ""
    ))
    print()

print("=" * 100)
print(f"  NCC hardware overhead (fixed, 80 units x 32 FMAs @ alpha=0.054):")
print(f"    Dynamic: {NCC_DYN_W*1e3:.2f} mW   Leakage: {NCC_LEAK_W*1e3:.2f} mW   Total: {(NCC_DYN_W+NCC_LEAK_W)*1e3:.2f} mW")
print("=" * 100)
