"""
compute_power_kernels.py
------------------------
Per-kernel power analysis for each workload/dataset combo.

For each combo, reads its rows of unified_eval/stats/unified_kernels.csv
(written by compute_unified.py: baseline and NCC per-launch stats paired by
trace kernel ID, cache counts repaired by repair_cache_stats.py, launch counts
from the trace's launch log), loads grid/block dimensions for each kernel ID
from the corresponding stats_ctx trace file, and writes:
  power_analysis/kernel_runs/<combo>/kernel_power.csv
  power_analysis/kernel_runs/<combo>/kernel_power.txt

Output is sorted by kernel_type (function name), then grid/block shape,
then invocation index. invocation_idx is the kernel's rank by trace kernel ID
among same-named simulated kernels; launch_count is its number of launches in
the full workload. (Earlier versions matched baseline and NCC rows by their
"<name>--<N>" labels, which count occurrences within one run and so paired
different kernels whenever the NCC run's filtered kernel list dropped an
earlier instance, and took the N-th stats_ctx launch as the kernel's shape.)

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

NCC_DYN_W  = 0.0282766
NCC_LEAK_W = 0.157266

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).parent
CACTI_DIR   = SCRIPT_DIR.parent
CONFIGS_DIR = CACTI_DIR / "configs"

# CLI args: an existing *.json -> NCC full-matrix manifest (switches the combo
# list / stats dir / stats_ctx map to the 19 new combos); any other existing
# path -> L2 cacti .out to use; any remaining token(s) -> workload filter
# (e.g. `igb`, `gcn_cora`, `egnn gin`). No filter = all.
_ARGV = sys.argv[1:]
_MANIFEST = next((a for a in _ARGV
                  if a.endswith(".json") and Path(a).exists()), None)
_PATH_ARGS = [a for a in _ARGV if a != _MANIFEST and Path(a).exists()]
_WL_FILTER = [a for a in _ARGV if a != _MANIFEST and not Path(a).exists()]
OUT_FILE    = Path(_PATH_ARGS[0]) if _PATH_ARGS \
              else CONFIGS_DIR / "cache_a100_baseline.cfg.out"
L1_OUT_FILE = CONFIGS_DIR / "cache_a100_l1.cfg.out"

STATS_DIR   = Path("/home/cory/accel-sim-framework/sim_run_12.8/"
                   "dissertation_sims/stats/converted")

TRACE_BASE  = Path("/home/cory/accel-sim-framework/hw_run/traces/dissertation_traces")

# Mapping: combo tag → stats_ctx file path (relative to TRACE_BASE)
_IGB_ARGS = ("dataset_size_tiny___num_layers_2___hidden_channels_128___fan_out_5_10"
            "___batch_size_256___epochs_4___max_iters_5")

STATS_CTX = {
    "egnn_cora":     TRACE_BASE / "EGNN/hashed_args_ee9575be706211aa3933a8cc5d8ed1b8/traces/stats_ctx_0x3ce54990",
    "egnn_kinship":  TRACE_BASE / "EGNN/hashed_args_1032ffa1fa7482d93b95a6e725e5618a/traces/stats_ctx_0xc845610",
    "gin_IMDBMULTI": TRACE_BASE / "GIN/__dataset_IMDBMULTI___epochs_10___iters_per_epoch_20/traces/stats_ctx_0x441fe040",
    "gin_MUTAG":     TRACE_BASE / "GIN/__dataset_MUTAG___epochs_10___iters_per_epoch_20/traces/stats_ctx_0x39edc5b0",
    "lgcn_gowalla":  TRACE_BASE / "LGCN/__decay_1e_4___lr_0_001___layer_3___seed_2020___dataset__gowalla____topks___20_____recdim_64___epochs_1/traces/stats_ctx_0x2d6e29c0",
    "lgcn_yelp2018": TRACE_BASE / "LGCN/__decay_1e_4___lr_0_001___layer_3___seed_2020___dataset__yelp2018____topks___20_____recdim_64___epochs_1/traces/stats_ctx_0x45421850",
    "igb_gcn_tiny":  TRACE_BASE / f"IGB/__model_type_gcn___{_IGB_ARGS}/traces/stats_ctx_0x644574637660",
    "igb_sage_tiny": TRACE_BASE / f"IGB/__model_type_sage___{_IGB_ARGS}/traces/stats_ctx_0x6058e3b62850",
    "igb_gat_tiny":  TRACE_BASE / f"IGB/__model_type_gat___{_IGB_ARGS}___num_heads_4/traces/stats_ctx_0x59eceac95080",
}

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
# NCC full-matrix override: when a manifest json is passed, replace the combo
# list / stats dir / stats_ctx map with the 19 new fullmatrix combos. The CACTI
# .out constants above are geometry-only and stay identical.
# ---------------------------------------------------------------------------
if _MANIFEST:
    import json
    _mf = json.load(open(_MANIFEST))["combos"]
    STATS_DIR  = Path("/home/cory/accel-sim-framework/sim_run_12.8/"
                      "fullmatrix_sims/stats/converted")
    _FM_TRACE_BASE = Path("/home/cory/accel-sim-framework/hw_run/traces/"
                          "fullmatrix_traces")
    STATS_CTX = {}
    WORKLOADS = []
    for _e in _mf:
        _tag = _e["combo"]                 # e.g. gcn_cora  (model_dataset)
        _model, _dataset = _tag.split("_", 1)
        WORKLOADS.append((_model, _dataset))
        _ctx_glob = sorted((_FM_TRACE_BASE / _e["arg_dir"] / "traces").glob("stats_ctx_*"))
        STATS_CTX[_tag] = _ctx_glob[0] if _ctx_glob else None
    print(f"NCC full-matrix mode: {len(WORKLOADS)} combos from {Path(_MANIFEST).name}")
    _KRUN_DIR = SCRIPT_DIR / "kernel_runs_fullmatrix"
else:
    _KRUN_DIR = SCRIPT_DIR / "kernel_runs"

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
# Parse stats_ctx: build grid/block lookup per function name
# Format: kernel-ID-ctx.trace.xz, func_name, gx, gy, gz, #blocks, bx, by, bz, #threads, ...
# ---------------------------------------------------------------------------
def load_grid_block(stats_ctx_path):
    """
    Returns dict: {func_name: [(kernel_id, gx,gy,gz, bx,by,bz), ...]} in launch order.
    Invocation N of func maps to list index N.
    kernel_id is the integer extracted from 'kernel-N-ctx...' in column 0.
    """
    lookup = {}
    with open(stats_ctx_path) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 9:
                continue
            kid_raw = row[0].strip()   # e.g. "kernel-17-ctx_0xc845610.trace.xz"
            func    = row[1].strip()
            try:
                kid = int(kid_raw.split("-")[1])
                gx, gy, gz = int(row[2]), int(row[3]), int(row[4])
                bx, by, bz = int(row[6]), int(row[7]), int(row[8])
            except (ValueError, IndexError):
                continue
            lookup.setdefault(func, []).append((kid, gx, gy, gz, bx, by, bz))
    return lookup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

UNIFIED_KERNELS = Path("/home/cory/research_figures/dissertation_figures/"
                       "unified_eval/stats/unified_kernels.csv")
# combo tag used here -> compute_unified config name
UNIFIED_CONFIG = {"gin_IMDBMULTI": "gin_imdb", "gin_MUTAG": "gin_mutag"}
_STATS = ["gpu_tot_sim_cycle", "L1_read_total_access", "L1_write_total_access",
          "L2_read_total_access", "L2_write_total_access"]


def load_unified(tag):
    """(kernels, base_rows, ncc_rows) for one combo from unified_kernels.csv.

    kernels: [(kernel_id, kernel_name, launch_count)] in kernel-ID order;
    base_rows/ncc_rows: {kernel_id: {converted-CSV stat: value}}; ncc_rows only
    for kernels with an NCC simulation.
    """
    config = UNIFIED_CONFIG.get(tag, tag)
    kernels, base_rows, ncc_rows = [], {}, {}
    with open(UNIFIED_KERNELS) as f:
        for r in csv.DictReader(f):
            if r["config"] != config:
                continue
            kid = int(r["kernel_id"])
            kernels.append((kid, r["kernel_name"], int(float(r["launches"]))))
            base_rows[kid] = {c: r[f"base_{c}"] for c in _STATS}
            if r["ncc_gpu_tot_sim_cycle"] != "":
                ncc_rows[kid] = {c: r[f"ncc_{c}"] for c in _STATS}
    if not kernels:
        raise SystemExit(f"{config} not in {UNIFIED_KERNELS}; run compute_unified.py")
    kernels.sort()
    return kernels, base_rows, ncc_rows

def kernel_power(row, total_cycles):
    cycles    = safe_float(row.get("gpu_tot_sim_cycle", 0))
    l1_reads  = safe_float(row.get("L1_read_total_access", 0))
    l1_writes = safe_float(row.get("L1_write_total_access", 0))
    l2_reads  = safe_float(row.get("L2_read_total_access", 0))
    l2_writes = safe_float(row.get("L2_write_total_access", 0))

    time_s = cycles / CLOCK_HZ
    l2_dyn_W = (l2_reads * E_READ_NJ    + l2_writes * E_WRITE_NJ)    * 1e-9 / time_s if time_s > 0 else 0.0
    l1_dyn_W = (l1_reads * L1_E_READ_NJ + l1_writes * L1_E_WRITE_NJ) * 1e-9 / time_s if time_s > 0 else 0.0

    frac = cycles / total_cycles if total_cycles > 0 else 0.0
    return {
        "cycles":    cycles,
        "l1_reads":  l1_reads, "l1_writes": l1_writes,
        "l2_reads":  l2_reads, "l2_writes": l2_writes,
        "l1_dyn_W":  l1_dyn_W, "l2_dyn_W":  l2_dyn_W,
        "l1_leak_W": LEAK_L1_TOTAL_W * frac,
        "l2_leak_W": LEAK_L2_TOTAL_W * frac,
        "total_W":   l1_dyn_W + l2_dyn_W + LEAK_L1_TOTAL_W * frac + LEAK_L2_TOTAL_W * frac,
    }

EMPTY = {k: 0.0 for k in ["cycles","l1_reads","l1_writes","l2_reads","l2_writes",
                            "l1_dyn_W","l2_dyn_W","l1_leak_W","l2_leak_W","total_W"]}

NO_SHAPE = (0, 0, 0, 0, 0, 0)

CSV_FIELDS = [
    "kernel_type", "kernel_id", "invocation_idx", "launch_count",
    "grid_x", "grid_y", "grid_z", "total_blocks",
    "block_x", "block_y", "block_z", "total_threads",
    "base_cycles", "base_l1_reads", "base_l1_writes",
    "base_l2_reads", "base_l2_writes",
    "base_l1_dyn_W", "base_l2_dyn_W",
    "base_l1_leak_W", "base_l2_leak_W", "base_full_total_W",
    "ncc_cycles", "ncc_l1_reads", "ncc_l1_writes",
    "ncc_l2_reads", "ncc_l2_writes",
    "ncc_l1_dyn_W", "ncc_l2_dyn_W",
    "ncc_l1_leak_W", "ncc_l2_leak_W",
    "ncc_hw_dyn_W", "ncc_hw_leak_W", "ncc_full_total_W",
    "mix_cycles", "mix_l1_reads", "mix_l1_writes",
    "mix_l2_reads", "mix_l2_writes",
    "mix_l1_dyn_W", "mix_l2_dyn_W",
    "mix_l1_leak_W", "mix_l2_leak_W",
    "mix_hw_dyn_W", "mix_hw_leak_W", "mix_full_total_W",
    "delta_l1_dyn_W", "delta_l2_dyn_W", "delta_full_total_W",
    "mix_delta_full_total_W",
]

# ---------------------------------------------------------------------------
# Text table helpers
# ---------------------------------------------------------------------------
HEADER_W = 200
FMT = ("{:<45} {:>4} {:>6} {:>5} {:>5} {:>5} {:>8} {:>7} {:>7} {:>7} {:>9}"
       " {:>8} {:>10} {:>10} {:>10} {:>10}"
       " {:>10} {:>10} {:>10} {:>10} {:>12}"
       " {:>10} {:>10} {:>10} {:>12}")

def txt_header(tag):
    lines = ["=" * HEADER_W,
             f"  Workload: {tag}",
             f"  Technology: {TECH_NM:.0f} nm    Clock: {CLOCK_HZ/1e9:.2f} GHz",
             f"  L2: E_read={E_READ_NJ} nJ  E_write={E_WRITE_NJ} nJ  Leak={LEAK_L2_TOTAL_W:.3f} W (80 slices)",
             f"  L1: E_read={L1_E_READ_NJ} nJ  E_write={L1_E_WRITE_NJ} nJ  Leak={LEAK_L1_TOTAL_W:.3f} W (108 SMs)",
             f"  NCC HW overhead (prorated): dyn={NCC_DYN_W*1e3:.2f} mW  leak={NCC_LEAK_W*1e3:.2f} mW",
             "=" * HEADER_W,
             FMT.format(
                 "Kernel type", "inv", "kid",
                 "gx", "gy", "gz", "blocks", "bx", "by", "bz", "threads",
                 "Config",
                 "L1 reads", "L1 writes", "L2 reads", "L2 writes",
                 "L1 Dyn(W)", "L2 Dyn(W)", "L1 Lk(W)", "L2 Lk(W)",
                 "FULL TOT(W)",
                 "NCC Dyn(W)", "NCC Lk(W)",
                 "NCC TOT(W)", "DELTA(W)"),
             "-" * HEADER_W]
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Process each combo
# ---------------------------------------------------------------------------
_workloads = [(m, d) for (m, d) in WORKLOADS
              if not _WL_FILTER
              or m in _WL_FILTER or f"{m}_{d}" in _WL_FILTER]
if _WL_FILTER:
    print(f"Workload filter: {_WL_FILTER} -> {[f'{m}_{d}' for m, d in _workloads]}")

for model, dataset in _workloads:
    tag = f"{model}_{dataset}"
    print(f"\nProcessing {tag} ...")

    kernels, base_rows, ncc_rows = load_unified(tag)

    total_base_cycles = sum(safe_float(r["gpu_tot_sim_cycle"]) for r in base_rows.values())
    # Include baseline cycles for kernels absent from NCC (0%-eligible, transparent to NCC)
    total_ncc_cycles  = sum(safe_float((ncc_rows.get(kid) or base_rows[kid])["gpu_tot_sim_cycle"])
                            for kid in base_rows)

    # Grid/block per trace kernel ID from stats_ctx
    shape_by_kid = {launch[0]: launch[1:]
                    for launches in load_grid_block(STATS_CTX[tag]).values()
                    for launch in launches}

    entries = []
    inv_counts = {}  # per-function rank by kernel ID

    for kid, func, launch_count in kernels:
        inv_idx = inv_counts.get(func, 0)
        inv_counts[func] = inv_idx + 1
        gx, gy, gz, bx, by, bz = shape_by_kid.get(kid, NO_SHAPE)

        b = kernel_power(base_rows[kid], total_base_cycles)
        n = kernel_power(ncc_rows[kid],  total_ncc_cycles) if kid in ncc_rows else dict(b)

        ncc_hw_dyn_W  = NCC_DYN_W  * (n["cycles"] / total_ncc_cycles) if total_ncc_cycles > 0 else 0.0
        ncc_hw_leak_W = NCC_LEAK_W * (n["cycles"] / total_ncc_cycles) if total_ncc_cycles > 0 else 0.0
        ncc_full_W    = n["total_W"] + ncc_hw_dyn_W + ncc_hw_leak_W
        delta_full_W  = ncc_full_W - b["total_W"]

        # Mixed: baseline L2 activity + NCC L1 activity + NCC hardware.
        # Time base = baseline kernel cycles.
        b_time_s      = b["cycles"] / CLOCK_HZ
        mix_l1_dyn_W  = (n["l1_reads"] * L1_E_READ_NJ + n["l1_writes"] * L1_E_WRITE_NJ) \
                        * 1e-9 / b_time_s if b_time_s > 0 else 0.0
        mix_l2_dyn_W  = b["l2_dyn_W"]
        mix_frac      = b["cycles"] / total_base_cycles if total_base_cycles > 0 else 0.0
        mix_hw_dyn_W  = NCC_DYN_W  * (b["cycles"] / total_base_cycles) if total_base_cycles > 0 else 0.0
        mix_hw_leak_W = NCC_LEAK_W * (b["cycles"] / total_base_cycles) if total_base_cycles > 0 else 0.0
        mix_l1_leak_W = LEAK_L1_TOTAL_W * mix_frac
        mix_l2_leak_W = LEAK_L2_TOTAL_W * mix_frac
        mix_full_W    = mix_l1_dyn_W + mix_l2_dyn_W + mix_l1_leak_W + mix_l2_leak_W \
                        + mix_hw_dyn_W + mix_hw_leak_W

        entries.append({
            "kernel_type":        func,
            "kernel_id":          kid,
            "invocation_idx":     inv_idx,
            "launch_count":       launch_count,
            "grid_x": gx, "grid_y": gy, "grid_z": gz,
            "total_blocks":       gx * gy * gz,
            "block_x": bx, "block_y": by, "block_z": bz,
            "total_threads":      bx * by * bz,
            "base_cycles":        b["cycles"],
            "base_l1_reads":      b["l1_reads"],  "base_l1_writes":  b["l1_writes"],
            "base_l2_reads":      b["l2_reads"],  "base_l2_writes":  b["l2_writes"],
            "base_l1_dyn_W":      b["l1_dyn_W"],  "base_l2_dyn_W":   b["l2_dyn_W"],
            "base_l1_leak_W":     b["l1_leak_W"], "base_l2_leak_W":  b["l2_leak_W"],
            "base_full_total_W":  b["total_W"],
            "ncc_cycles":         n["cycles"],
            "ncc_l1_reads":       n["l1_reads"],  "ncc_l1_writes":   n["l1_writes"],
            "ncc_l2_reads":       n["l2_reads"],  "ncc_l2_writes":   n["l2_writes"],
            "ncc_l1_dyn_W":       n["l1_dyn_W"],  "ncc_l2_dyn_W":    n["l2_dyn_W"],
            "ncc_l1_leak_W":      n["l1_leak_W"], "ncc_l2_leak_W":   n["l2_leak_W"],
            "ncc_hw_dyn_W":       ncc_hw_dyn_W,   "ncc_hw_leak_W":   ncc_hw_leak_W,
            "ncc_full_total_W":   ncc_full_W,
            # mixed
            "mix_l1_reads":       n["l1_reads"],  "mix_l1_writes":   n["l1_writes"],
            "mix_l2_reads":       b["l2_reads"],  "mix_l2_writes":   b["l2_writes"],
            "mix_cycles":         b["cycles"],
            "mix_l1_dyn_W":       mix_l1_dyn_W,   "mix_l2_dyn_W":    mix_l2_dyn_W,
            "mix_l1_leak_W":      mix_l1_leak_W,  "mix_l2_leak_W":   mix_l2_leak_W,
            "mix_hw_dyn_W":       mix_hw_dyn_W,   "mix_hw_leak_W":   mix_hw_leak_W,
            "mix_full_total_W":   mix_full_W,
            "delta_l1_dyn_W":     n["l1_dyn_W"] - b["l1_dyn_W"],
            "delta_l2_dyn_W":     n["l2_dyn_W"] - b["l2_dyn_W"],
            "delta_full_total_W": delta_full_W,
            "mix_delta_full_total_W": mix_full_W - b["total_W"],
        })

    # Sort by kernel_type → (gx,gy,gz,bx,by,bz) → invocation_idx
    entries.sort(key=lambda e: (e["kernel_type"],
                                 e["grid_x"], e["grid_y"], e["grid_z"],
                                 e["block_x"], e["block_y"], e["block_z"],
                                 e["invocation_idx"]))

    # Write outputs
    out_dir = _KRUN_DIR / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "kernel_power.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(entries)

    txt_lines = [txt_header(tag)]
    prev_type = None
    prev_shape = None
    for e in entries:
        ktype = e["kernel_type"]
        shape = (e["grid_x"], e["grid_y"], e["grid_z"],
                 e["block_x"], e["block_y"], e["block_z"])

        # Separator between kernel types or shapes
        if ktype != prev_type or shape != prev_shape:
            if prev_type is not None:
                txt_lines.append("")
            prev_type, prev_shape = ktype, shape

        kshort = ktype[-45:] if len(ktype) > 45 else ktype

        def row_fmt(config, lr, lw, zr, zw, l1d, l2d, l1l, l2l, tot,
                    nd=None, nl=None, nt=None, delta=None):
            show = config == "baseline"
            return FMT.format(
                kshort if show else "",
                e["invocation_idx"] if show else "",
                e["kernel_id"] if show else "",
                e["grid_x"] if show else "",
                e["grid_y"] if show else "",
                e["grid_z"] if show else "",
                e["total_blocks"] if show else "",
                e["block_x"] if show else "",
                e["block_y"] if show else "",
                e["block_z"] if show else "",
                e["total_threads"] if show else "",
                config,
                f"{lr:+.0f}" if config == "delta" else f"{lr:.0f}",
                f"{lw:+.0f}" if config == "delta" else f"{lw:.0f}",
                f"{zr:+.0f}" if config == "delta" else f"{zr:.0f}",
                f"{zw:+.0f}" if config == "delta" else f"{zw:.0f}",
                f"{l1d:+.4f}" if config == "delta" else f"{l1d:.4f}",
                f"{l2d:+.4f}" if config == "delta" else f"{l2d:.4f}",
                f"{l1l:.4f}", f"{l2l:.4f}",
                f"{tot:+.4f}" if config == "delta" else f"{tot:.4f}",
                f"{nd:.4f}" if nd is not None else "—",
                f"{nl:.4f}" if nl is not None else "—",
                f"{nt:.4f}" if nt is not None else "—",
                f"{delta:+.4f}" if delta is not None else "")

        txt_lines.append(row_fmt(
            "baseline",
            e["base_l1_reads"], e["base_l1_writes"],
            e["base_l2_reads"], e["base_l2_writes"],
            e["base_l1_dyn_W"], e["base_l2_dyn_W"],
            e["base_l1_leak_W"], e["base_l2_leak_W"],
            e["base_full_total_W"]))
        txt_lines.append(row_fmt(
            "ncc_fp3",
            e["ncc_l1_reads"], e["ncc_l1_writes"],
            e["ncc_l2_reads"], e["ncc_l2_writes"],
            e["ncc_l1_dyn_W"], e["ncc_l2_dyn_W"],
            e["ncc_l1_leak_W"], e["ncc_l2_leak_W"],
            e["ncc_full_total_W"],
            e["ncc_hw_dyn_W"], e["ncc_hw_leak_W"],
            e["ncc_full_total_W"],
            e["delta_full_total_W"]))
        txt_lines.append(row_fmt(
            "mixed",
            e["mix_l1_reads"], e["mix_l1_writes"],
            e["mix_l2_reads"], e["mix_l2_writes"],
            e["mix_l1_dyn_W"], e["mix_l2_dyn_W"],
            e["mix_l1_leak_W"], e["mix_l2_leak_W"],
            e["mix_full_total_W"],
            e["mix_hw_dyn_W"], e["mix_hw_leak_W"],
            e["mix_full_total_W"],
            e["mix_delta_full_total_W"]))
        txt_lines.append(row_fmt(
            "delta",
            e["ncc_l1_reads"]  - e["base_l1_reads"],
            e["ncc_l1_writes"] - e["base_l1_writes"],
            e["ncc_l2_reads"]  - e["base_l2_reads"],
            e["ncc_l2_writes"] - e["base_l2_writes"],
            e["delta_l1_dyn_W"], e["delta_l2_dyn_W"],
            0.0, 0.0,
            e["delta_full_total_W"]))

    txt_lines.append("\n" + "=" * HEADER_W)
    txt_path = out_dir / "kernel_power.txt"
    txt_path.write_text("\n".join(txt_lines) + "\n")

    print(f"  {len(entries)} kernels → {csv_path}")
    print(f"               → {txt_path}")

print("\nDone.")
