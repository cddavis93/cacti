"""
compute_power_kernels.py
------------------------
Per-kernel power analysis for each workload/dataset combo.

For each combo, reads the baseline and ncc_fp3 accel-sim stats CSVs,
matches kernels by name, and writes:
  power_analysis/kernel_runs/<combo>/kernel_power.csv
  power_analysis/kernel_runs/<combo>/kernel_power.txt

CACTI constants are loaded from the same .out files as compute_power.py.

Usage:
  python3 power_analysis/compute_power_kernels.py [path/to/l2.out]
"""

import csv
import sys
from pathlib import Path
from io import StringIO

# ---------------------------------------------------------------------------
# CACTI config-matching criteria
# ---------------------------------------------------------------------------
L2_MATCH_CAPACITY_B = 524288
L2_MATCH_ASSOC      = 16
L2_MATCH_OUTPUT_W   = 1024

L1_MATCH_CAPACITY_B = 131072
L1_MATCH_ASSOC      = 4
L1_MATCH_OUTPUT_W   = 1024

# ---------------------------------------------------------------------------
# Fixed constants
# ---------------------------------------------------------------------------
N_L2_SLICES = 80
N_L1_SMS    = 108
CLOCK_HZ    = 1.41e9

NCC_DYN_W          = 0.0282766
NCC_LEAK_W         = 0.157266

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).parent
CACTI_DIR   = SCRIPT_DIR.parent
CONFIGS_DIR = CACTI_DIR / "configs"
OUT_FILE    = Path(sys.argv[1]) if len(sys.argv) > 1 \
              else CONFIGS_DIR / "cache_a100_baseline.cfg.out"
L1_OUT_FILE = CONFIGS_DIR / "cache_a100_l1.cfg.out"

STATS_DIR   = Path("/home/cory/accel-sim-framework/sim_run_12.8/"
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
# Load CACTI .out constants
# ---------------------------------------------------------------------------
def load_cacti_out(path, cap_b, assoc, outw):
    match = None
    with open(path) as f:
        for row in csv.DictReader(f, skipinitialspace=True):
            try:
                c = int(float(row["Capacity (bytes)"]))
                a = int(float(row["Associativity"]))
                w = int(float(row["Output width (bits)"]))
            except (KeyError, ValueError):
                continue
            if c == cap_b and a == assoc and w == outw:
                match = row
    if match is None:
        raise RuntimeError(f"No matching row in {path}")
    return match

l2 = load_cacti_out(OUT_FILE,    L2_MATCH_CAPACITY_B, L2_MATCH_ASSOC, L2_MATCH_OUTPUT_W)
l1 = load_cacti_out(L1_OUT_FILE, L1_MATCH_CAPACITY_B, L1_MATCH_ASSOC, L1_MATCH_OUTPUT_W)

E_READ_NJ        = float(l2["Dynamic read energy (nJ)"])
E_WRITE_NJ       = float(l2["Dynamic write energy (nJ)"])
LEAK_PER_SLICE_W = float(l2["Standby leakage per bank(mW)"]) * 1e-3
TECH_NM          = float(l2["Tech node (nm)"])
L2_AREA_MM2      = float(l2["Area (mm2)"])
LEAK_L2_TOTAL_W  = LEAK_PER_SLICE_W * N_L2_SLICES

L1_E_READ_NJ     = float(l1["Dynamic read energy (nJ)"])
L1_E_WRITE_NJ    = float(l1["Dynamic write energy (nJ)"])
L1_LEAK_PER_SM_W = float(l1["Standby leakage per bank(mW)"]) * 1e-3
L1_AREA_MM2      = float(l1["Area (mm2)"])
LEAK_L1_TOTAL_W  = L1_LEAK_PER_SM_W * N_L1_SMS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def load_csv_by_kernel(path):
    """Return ordered list of kernel names and dict keyed by kernel_name."""
    rows = {}
    order = []
    with open(path) as f:
        for row in csv.DictReader(f):
            name = row["kernel_name"]
            rows[name] = row
            if name not in order:
                order.append(name)
    return order, rows

def kernel_power(row, total_cycles):
    """Compute power components for one kernel row."""
    cycles   = safe_float(row.get("gpu_tot_sim_cycle", 0))
    l1_reads = safe_float(row.get("L1_read_total_access", 0))
    l1_writes= safe_float(row.get("L1_write_total_access", 0))
    l2_reads = safe_float(row.get("L2_read_total_access", 0))
    l2_writes= safe_float(row.get("L2_write_total_access", 0))

    time_s = cycles / CLOCK_HZ

    l2_dyn_W = (l2_reads * E_READ_NJ    + l2_writes * E_WRITE_NJ)    * 1e-9 / time_s if time_s > 0 else 0.0
    l1_dyn_W = (l1_reads * L1_E_READ_NJ + l1_writes * L1_E_WRITE_NJ) * 1e-9 / time_s if time_s > 0 else 0.0

    frac = cycles / total_cycles if total_cycles > 0 else 0.0
    l2_leak_W = LEAK_L2_TOTAL_W * frac
    l1_leak_W = LEAK_L1_TOTAL_W * frac

    return {
        "cycles":    cycles,
        "l1_reads":  l1_reads,
        "l1_writes": l1_writes,
        "l2_reads":  l2_reads,
        "l2_writes": l2_writes,
        "l1_dyn_W":  l1_dyn_W,
        "l2_dyn_W":  l2_dyn_W,
        "l1_leak_W": l1_leak_W,
        "l2_leak_W": l2_leak_W,
        "total_W":   l1_dyn_W + l2_dyn_W + l1_leak_W + l2_leak_W,
    }

EMPTY = {k: 0.0 for k in
         ["cycles","l1_reads","l1_writes","l2_reads","l2_writes",
          "l1_dyn_W","l2_dyn_W","l1_leak_W","l2_leak_W","total_W"]}

CSV_FIELDS = [
    "kernel_name",
    "base_cycles", "base_l1_reads", "base_l1_writes",
    "base_l2_reads", "base_l2_writes",
    "base_l1_dyn_W", "base_l2_dyn_W",
    "base_l1_leak_W", "base_l2_leak_W", "base_full_total_W",
    "ncc_cycles", "ncc_l1_reads", "ncc_l1_writes",
    "ncc_l2_reads", "ncc_l2_writes",
    "ncc_l1_dyn_W", "ncc_l2_dyn_W",
    "ncc_l1_leak_W", "ncc_l2_leak_W",
    "ncc_hw_dyn_W", "ncc_hw_leak_W", "ncc_full_total_W",
    "delta_l1_dyn_W", "delta_l2_dyn_W", "delta_full_total_W",
]

# ---------------------------------------------------------------------------
# Process each workload/dataset combo
# ---------------------------------------------------------------------------
HEADER_W = 175
FMT = "{:<55} {:>8} {:>12} {:>12} {:>12} {:>12} {:>10} {:>10} {:>10} {:>10} {:>10} {:>10} {:>12}"

def make_header():
    lines = []
    lines.append("=" * HEADER_W)
    lines.append(f"  Technology : {TECH_NM:.0f} nm    Clock: {CLOCK_HZ/1e9:.2f} GHz")
    lines.append(f"  L2 .out    : {OUT_FILE}")
    lines.append(f"    E_read={E_READ_NJ} nJ  E_write={E_WRITE_NJ} nJ  "
                 f"Leak/slice={LEAK_PER_SLICE_W*1e3:.3f} mW ({LEAK_L2_TOTAL_W:.3f} W x{N_L2_SLICES})")
    lines.append(f"  L1 .out    : {L1_OUT_FILE}")
    lines.append(f"    E_read={L1_E_READ_NJ} nJ  E_write={L1_E_WRITE_NJ} nJ  "
                 f"Leak/SM={L1_LEAK_PER_SM_W*1e3:.3f} mW ({LEAK_L1_TOTAL_W:.3f} W x{N_L1_SMS})")
    lines.append(f"  NCC HW overhead (prorated per kernel): "
                 f"dyn={NCC_DYN_W*1e3:.2f} mW  leak={NCC_LEAK_W*1e3:.2f} mW")
    lines.append("=" * HEADER_W)
    lines.append(FMT.format(
        "Kernel", "Config",
        "L1 reads", "L1 writes", "L2 reads", "L2 writes",
        "L1 Dyn(W)", "L2 Dyn(W)", "L1 Lk(W)", "L2 Lk(W)",
        "NCC Dyn(W)", "NCC Lk(W)", "FULL TOT(W)"
    ))
    lines.append("-" * HEADER_W)
    return "\n".join(lines)

for model, dataset in WORKLOADS:
    tag = f"{model}_{dataset}"
    print(f"\nProcessing {tag} ...")

    base_path = STATS_DIR / f"baseline_{tag}_converted.csv"
    ncc_path  = STATS_DIR / f"ncc_fp3_{tag}_converted.csv"

    base_order, base_rows = load_csv_by_kernel(base_path)
    ncc_order,  ncc_rows  = load_csv_by_kernel(ncc_path)

    # Total cycles for prorating leakage and NCC HW cost
    total_base_cycles = sum(safe_float(r["gpu_tot_sim_cycle"]) for r in base_rows.values())
    total_ncc_cycles  = sum(safe_float(r["gpu_tot_sim_cycle"]) for r in ncc_rows.values())

    # Union of kernel names, baseline order first, then any NCC-only kernels
    all_kernels = list(base_order)
    for k in ncc_order:
        if k not in all_kernels:
            all_kernels.append(k)

    # Build per-kernel result rows
    csv_rows = []
    txt_lines = [make_header(), f"\n  Workload: {tag}\n", "-" * HEADER_W]

    for kname in all_kernels:
        b = kernel_power(base_rows[kname], total_base_cycles) if kname in base_rows else dict(EMPTY)
        n = kernel_power(ncc_rows[kname],  total_ncc_cycles)  if kname in ncc_rows  else dict(EMPTY)

        ncc_hw_dyn_W  = NCC_DYN_W  * (n["cycles"] / total_ncc_cycles) if total_ncc_cycles > 0 else 0.0
        ncc_hw_leak_W = NCC_LEAK_W * (n["cycles"] / total_ncc_cycles) if total_ncc_cycles > 0 else 0.0
        ncc_full_W    = n["total_W"] + ncc_hw_dyn_W + ncc_hw_leak_W

        csv_rows.append({
            "kernel_name":      kname,
            "base_cycles":      b["cycles"],
            "base_l1_reads":    b["l1_reads"],
            "base_l1_writes":   b["l1_writes"],
            "base_l2_reads":    b["l2_reads"],
            "base_l2_writes":   b["l2_writes"],
            "base_l1_dyn_W":    b["l1_dyn_W"],
            "base_l2_dyn_W":    b["l2_dyn_W"],
            "base_l1_leak_W":   b["l1_leak_W"],
            "base_l2_leak_W":   b["l2_leak_W"],
            "base_full_total_W":b["total_W"],
            "ncc_cycles":       n["cycles"],
            "ncc_l1_reads":     n["l1_reads"],
            "ncc_l1_writes":    n["l1_writes"],
            "ncc_l2_reads":     n["l2_reads"],
            "ncc_l2_writes":    n["l2_writes"],
            "ncc_l1_dyn_W":     n["l1_dyn_W"],
            "ncc_l2_dyn_W":     n["l2_dyn_W"],
            "ncc_l1_leak_W":    n["l1_leak_W"],
            "ncc_l2_leak_W":    n["l2_leak_W"],
            "ncc_hw_dyn_W":     ncc_hw_dyn_W,
            "ncc_hw_leak_W":    ncc_hw_leak_W,
            "ncc_full_total_W": ncc_full_W,
            "delta_l1_dyn_W":   n["l1_dyn_W"] - b["l1_dyn_W"],
            "delta_l2_dyn_W":   n["l2_dyn_W"] - b["l2_dyn_W"],
            "delta_full_total_W": ncc_full_W - b["total_W"],
        })

        # Shorten kernel name for display (trim to 55 chars)
        kshort = kname[:55]

        txt_lines.append(FMT.format(
            kshort, "baseline",
            f"{b['l1_reads']:.0f}", f"{b['l1_writes']:.0f}",
            f"{b['l2_reads']:.0f}", f"{b['l2_writes']:.0f}",
            f"{b['l1_dyn_W']:.4f}", f"{b['l2_dyn_W']:.4f}",
            f"{b['l1_leak_W']:.4f}", f"{b['l2_leak_W']:.4f}",
            "—", "—",
            f"{b['total_W']:.4f}"
        ))
        txt_lines.append(FMT.format(
            "", "ncc_fp3",
            f"{n['l1_reads']:.0f}", f"{n['l1_writes']:.0f}",
            f"{n['l2_reads']:.0f}", f"{n['l2_writes']:.0f}",
            f"{n['l1_dyn_W']:.4f}", f"{n['l2_dyn_W']:.4f}",
            f"{n['l1_leak_W']:.4f}", f"{n['l2_leak_W']:.4f}",
            f"{ncc_hw_dyn_W:.4f}", f"{ncc_hw_leak_W:.4f}",
            f"{ncc_full_W:.4f}"
        ))
        txt_lines.append(FMT.format(
            "", "delta",
            f"{n['l1_reads']-b['l1_reads']:+.0f}",
            f"{n['l1_writes']-b['l1_writes']:+.0f}",
            f"{n['l2_reads']-b['l2_reads']:+.0f}",
            f"{n['l2_writes']-b['l2_writes']:+.0f}",
            f"{n['l1_dyn_W']-b['l1_dyn_W']:+.4f}",
            f"{n['l2_dyn_W']-b['l2_dyn_W']:+.4f}",
            "—", "—", "—", "—",
            f"{ncc_full_W - b['total_W']:+.4f}"
        ))
        txt_lines.append("")

    txt_lines.append("=" * HEADER_W)

    # Write outputs
    out_dir = SCRIPT_DIR / "kernel_runs" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "kernel_power.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(csv_rows)

    txt_path = out_dir / "kernel_power.txt"
    txt_path.write_text("\n".join(txt_lines) + "\n")

    print(f"  {len(csv_rows)} kernels → {csv_path}")
    print(f"               → {txt_path}")

print("\nDone.")
