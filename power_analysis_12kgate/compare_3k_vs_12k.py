"""
compare_3k_vs_12k.py
---------------------
Compares NCC hardware power/energy and system-level totals between the
3000-gate baseline (power_analysis/) and the 12000-gate variant
(power_analysis_12kgate/), both already computed by their respective
compute_power.py / compute_power_kernels.py scripts.

Answers: does raising FMA_GATE_COUNT from 3000 to 12000 (the literature-
grounded range found to be more defensible than the original unsourced
3000 placeholder) cause a significant change in total system power/energy?

Self-check: verifies every column in both power_results.csv (and each
kernel_power.csv) is identical between the two runs EXCEPT the columns
that depend on NCC hardware, confirming gate count didn't leak into the
gate-count-independent L1/L2 numbers.

Usage:
  python3 power_analysis_12kgate/compare_3k_vs_12k.py

Writes:
  power_analysis_12kgate/compare_3k_vs_12k.txt
  power_analysis_12kgate/compare_3k_vs_12k.csv
"""

import csv
from pathlib import Path
from io import StringIO

SCRIPT_DIR   = Path(__file__).parent
CACTI_DIR    = SCRIPT_DIR.parent
DIR_3K       = CACTI_DIR / "power_analysis"
DIR_12K      = SCRIPT_DIR

CLOCK_HZ = 1.41e9

WORKLOADS = [
    ("egnn", "cora"),
    ("egnn", "kinship"),
    ("gin",  "IMDBMULTI"),
    ("gin",  "MUTAG"),
    ("lgcn", "gowalla"),
    ("lgcn", "yelp2018"),
]

# Columns in power_results.csv that legitimately differ between the two
# gate-count runs (everything else must be identical).
NCC_DEPENDENT_WORKLOAD_COLS = {
    "ncc_hw_dyn_W", "ncc_hw_leak_W", "ncc_full_total_W",
    "ncc_unit_area_mm2", "ncc_total_area_mm2", "system_total_area_mm2",
    "mix_hw_dyn_W", "mix_hw_leak_W", "mix_full_total_W",
    "delta_full_total_W", "mix_delta_full_total_W",
}

# Columns in kernel_power.csv that legitimately differ.
NCC_DEPENDENT_KERNEL_COLS = {
    "ncc_hw_dyn_W", "ncc_hw_leak_W", "ncc_full_total_W",
    "mix_hw_dyn_W", "mix_hw_leak_W", "mix_full_total_W",
    "delta_full_total_W", "mix_delta_full_total_W",
}

FLOAT_TOL = 1e-9  # absolute tolerance for "identical" float comparison


def safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def load_csv_rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def diff_columns(rows_a, rows_b, exempt_cols, key_col=None):
    """Return list of (row_idx_or_key, col, val_a, val_b) mismatches outside exempt_cols."""
    mismatches = []
    for i, (ra, rb) in enumerate(zip(rows_a, rows_b)):
        key = ra.get(key_col, i) if key_col else i
        for col in ra:
            if col in exempt_cols:
                continue
            va, vb = ra.get(col), rb.get(col)
            fa, fb = safe_float(va), safe_float(vb)
            if fa is not None and fb is not None:
                if abs(fa - fb) > FLOAT_TOL:
                    mismatches.append((key, col, va, vb))
            elif va != vb:
                mismatches.append((key, col, va, vb))
    return mismatches


# ---------------------------------------------------------------------------
# Self-check: power_results.csv
# ---------------------------------------------------------------------------
rows_3k  = load_csv_rows(DIR_3K / "power_results.csv")
rows_12k = load_csv_rows(DIR_12K / "power_results.csv")
wl_mismatches = diff_columns(rows_3k, rows_12k, NCC_DEPENDENT_WORKLOAD_COLS, key_col="workload")

# ---------------------------------------------------------------------------
# Self-check: kernel_power.csv per workload
# ---------------------------------------------------------------------------
kernel_mismatches = {}
for model, dataset in WORKLOADS:
    tag = f"{model}_{dataset}"
    k3k  = load_csv_rows(DIR_3K  / "kernel_runs" / tag / "kernel_power.csv")
    k12k = load_csv_rows(DIR_12K / "kernel_runs" / tag / "kernel_power.csv")
    mism = diff_columns(k3k, k12k, NCC_DEPENDENT_KERNEL_COLS, key_col="kernel_type")
    if mism:
        kernel_mismatches[tag] = mism

# ---------------------------------------------------------------------------
# NCC hardware constants (3K vs 12K) — read directly off the workload rows
# (identical across all workloads/configs within a run since NCC hardware
# power doesn't depend on workload, only on the gate-count build).
# ---------------------------------------------------------------------------
ncc_dyn_3k  = float(rows_3k[0]["ncc_hw_dyn_W"])
ncc_leak_3k = float(rows_3k[0]["ncc_hw_leak_W"])
ncc_dyn_12k  = float(rows_12k[0]["ncc_hw_dyn_W"])
ncc_leak_12k = float(rows_12k[0]["ncc_hw_leak_W"])
ncc_area_unit_3k  = float(rows_3k[0]["ncc_unit_area_mm2"])
ncc_area_total_3k = float(rows_3k[0]["ncc_total_area_mm2"])
ncc_area_unit_12k  = float(rows_12k[0]["ncc_unit_area_mm2"])
ncc_area_total_12k = float(rows_12k[0]["ncc_total_area_mm2"])

ncc_total_3k  = ncc_dyn_3k + ncc_leak_3k
ncc_total_12k = ncc_dyn_12k + ncc_leak_12k

# ---------------------------------------------------------------------------
# Render report
# ---------------------------------------------------------------------------
buf = StringIO()


def emit(*args, **kwargs):
    print(*args, **kwargs)
    print(*args, **kwargs, file=buf)


W = 130
emit("=" * W)
emit("  3K-gate vs 12K-gate NCC comparison  (FMA_GATE_COUNT = 3000 vs 12000)")
emit("=" * W)
emit()

# --- Self-check summary -----------------------------------------------------
emit("SELF-CHECK: gate-count-independent columns (L1/L2 cache power, cycles, reads/writes)")
emit("-" * W)
if not wl_mismatches and not kernel_mismatches:
    emit("  PASS - all non-NCC columns identical between 3K and 12K runs, in power_results.csv")
    emit("         and in every kernel_power.csv (6/6 workloads).")
else:
    if wl_mismatches:
        emit(f"  FAIL - {len(wl_mismatches)} unexpected mismatch(es) in power_results.csv:")
        for key, col, va, vb in wl_mismatches[:20]:
            emit(f"    workload={key} col={col}: 3K={va} 12K={vb}")
    for tag, mism in kernel_mismatches.items():
        emit(f"  FAIL - {len(mism)} unexpected mismatch(es) in kernel_runs/{tag}/kernel_power.csv:")
        for key, col, va, vb in mism[:10]:
            emit(f"    kernel={key} col={col}: 3K={va} 12K={vb}")
emit()

# --- Section A: isolated NCC hardware ---------------------------------------
emit("SECTION A - Isolated NCC hardware (workload-independent)")
emit("-" * W)
FMT_A = "{:<22} {:>14} {:>14} {:>10}"
emit(FMT_A.format("Quantity", "3K gates", "12K gates", "ratio"))
emit(FMT_A.format("NCC dyn power (W)", f"{ncc_dyn_3k:.7f}", f"{ncc_dyn_12k:.7f}", f"{ncc_dyn_12k/ncc_dyn_3k:.4f}"))
emit(FMT_A.format("NCC leak power (W)", f"{ncc_leak_3k:.7f}", f"{ncc_leak_12k:.7f}", f"{ncc_leak_12k/ncc_leak_3k:.4f}"))
emit(FMT_A.format("NCC total power (W)", f"{ncc_total_3k:.7f}", f"{ncc_total_12k:.7f}", f"{ncc_total_12k/ncc_total_3k:.4f}"))
emit(FMT_A.format("NCC unit area (mm2)", f"{ncc_area_unit_3k:.7f}", f"{ncc_area_unit_12k:.7f}", f"{ncc_area_unit_12k/ncc_area_unit_3k:.4f}"))
emit(FMT_A.format("NCC total area (mm2)", f"{ncc_area_total_3k:.7f}", f"{ncc_area_total_12k:.7f}", f"{ncc_area_total_12k/ncc_area_total_3k:.4f}"))
emit()
emit("  (Deterministic: every NCC quantity in ncc.cc's model_ncc() is exactly linear in")
emit("   FMA_GATE_COUNT, so 12000/3000 = 4.0x is expected and confirmed above.)")
emit()

emit("  Per-workload NCC-hardware-only energy (dyn+leak power x kernel-launch duration):")
emit("  " + "-" * (W - 2))
FMT_E = "{:<16} {:>10} {:>16} {:>16} {:>16} {:>16}"
emit(FMT_E.format("Workload", "Config", "3K energy (J)", "12K energy (J)", "delta (J)", "ratio"))
energy_rows = []
for r3, r12 in zip(rows_3k, rows_12k):
    tag = r3["workload"]
    for cfg, cyc_col in (("ncc_fp3", "ncc_cycles"), ("mixed", "mix_cycles")):
        cycles = float(r3[cyc_col])  # identical between 3K/12K runs (same accel-sim traces)
        time_s = cycles / CLOCK_HZ
        e3  = ncc_total_3k  * time_s
        e12 = ncc_total_12k * time_s
        emit(FMT_E.format(tag, cfg, f"{e3:.6e}", f"{e12:.6e}", f"{e12-e3:.6e}", f"{e12/e3:.4f}" if e3 > 0 else "n/a"))
        energy_rows.append({"workload": tag, "config": cfg, "ncc_energy_3k_J": e3,
                             "ncc_energy_12k_J": e12, "ncc_energy_delta_J": e12 - e3,
                             "ncc_energy_ratio": e12 / e3 if e3 > 0 else None})
emit()

# --- Section B: system-level propagation ------------------------------------
emit("SECTION B - System-level total power/energy propagation (baseline / ncc_fp3 / mixed)")
emit("-" * W)
FMT_B = "{:<16} {:>10} {:>12} {:>12} {:>10} {:>9} {:>14} {:>14} {:>10}"
emit(FMT_B.format("Workload", "Config", "3K W", "12K W", "d(W)", "%chg", "3K E(J)", "12K E(J)", "%chg E"))

system_rows = []
for r3, r12 in zip(rows_3k, rows_12k):
    tag = r3["workload"]
    for cfg, w_col, cyc_col in (
        ("baseline", "base_full_total_W", "base_cycles"),
        ("ncc_fp3",  "ncc_full_total_W",  "ncc_cycles"),
        ("mixed",    "mix_full_total_W",  "mix_cycles"),
    ):
        w3, w12 = float(r3[w_col]), float(r12[w_col])
        cycles = float(r3[cyc_col])
        time_s = cycles / CLOCK_HZ
        e3, e12 = w3 * time_s, w12 * time_s
        pct_w = (w12 - w3) / w3 * 100 if w3 != 0 else 0.0
        pct_e = (e12 - e3) / e3 * 100 if e3 != 0 else 0.0
        emit(FMT_B.format(tag, cfg, f"{w3:.4f}", f"{w12:.4f}", f"{w12-w3:+.4f}", f"{pct_w:+.2f}%",
                           f"{e3:.4e}", f"{e12:.4e}", f"{pct_e:+.2f}%"))
        system_rows.append({"workload": tag, "config": cfg, "full_total_W_3k": w3,
                             "full_total_W_12k": w12, "delta_W": w12 - w3, "pct_change_W": pct_w,
                             "full_total_energy_J_3k": e3, "full_total_energy_J_12k": e12,
                             "pct_change_energy": pct_e})
    emit()
emit("  Note: 'baseline' rows are identical (0.00%) between the two runs by construction -")
emit("  the baseline config excludes NCC hardware entirely (base_full_total_W has no NCC term).")
emit()

# --- Section C: significance verdict ----------------------------------------
emit("SECTION C - Significance verdict")
emit("-" * W)
FMT_C = "{:<16} {:>16} {:>16} {:>16} {:>16}"
emit(FMT_C.format("Workload", "NCC share 3K", "NCC share 12K", "NCC share 3K", "NCC share 12K"))
emit(FMT_C.format("", "(ncc_fp3, %)", "(ncc_fp3, %)", "(mixed, %)", "(mixed, %)"))

share_rows = []
sum_ncc3_a = sum_tot3_a = sum_ncc12_a = sum_tot12_a = 0.0
sum_ncc3_m = sum_tot3_m = sum_ncc12_m = sum_tot12_m = 0.0
for r3, r12 in zip(rows_3k, rows_12k):
    tag = r3["workload"]
    ncc_full_3k, ncc_full_12k = float(r3["ncc_full_total_W"]), float(r12["ncc_full_total_W"])
    mix_full_3k, mix_full_12k = float(r3["mix_full_total_W"]), float(r12["mix_full_total_W"])
    share_ncc_3k  = ncc_total_3k  / ncc_full_3k  * 100 if ncc_full_3k  else 0.0
    share_ncc_12k = ncc_total_12k / ncc_full_12k * 100 if ncc_full_12k else 0.0
    share_mix_3k  = ncc_total_3k  / mix_full_3k  * 100 if mix_full_3k  else 0.0
    share_mix_12k = ncc_total_12k / mix_full_12k * 100 if mix_full_12k else 0.0
    emit(FMT_C.format(tag, f"{share_ncc_3k:.3f}", f"{share_ncc_12k:.3f}",
                       f"{share_mix_3k:.3f}", f"{share_mix_12k:.3f}"))
    share_rows.append({"workload": tag, "ncc_share_pct_ncc_fp3_3k": share_ncc_3k,
                        "ncc_share_pct_ncc_fp3_12k": share_ncc_12k,
                        "ncc_share_pct_mixed_3k": share_mix_3k,
                        "ncc_share_pct_mixed_12k": share_mix_12k})
    sum_ncc3_a += ncc_total_3k; sum_tot3_a += ncc_full_3k
    sum_ncc12_a += ncc_total_12k; sum_tot12_a += ncc_full_12k
    sum_ncc3_m += ncc_total_3k; sum_tot3_m += mix_full_3k
    sum_ncc12_m += ncc_total_12k; sum_tot12_m += mix_full_12k

avg_share_ncc_3k  = sum_ncc3_a  / sum_tot3_a  * 100 if sum_tot3_a  else 0.0
avg_share_ncc_12k = sum_ncc12_a / sum_tot12_a * 100 if sum_tot12_a else 0.0
avg_share_mix_3k  = sum_ncc3_m  / sum_tot3_m  * 100 if sum_tot3_m  else 0.0
avg_share_mix_12k = sum_ncc12_m / sum_tot12_m * 100 if sum_tot12_m else 0.0
emit("-" * W)
emit(FMT_C.format("AVG (power-wtd)", f"{avg_share_ncc_3k:.3f}", f"{avg_share_ncc_12k:.3f}",
                   f"{avg_share_mix_3k:.3f}", f"{avg_share_mix_12k:.3f}"))
emit()

avg_pct_change_ncc_fp3 = sum(r["pct_change_W"] for r in system_rows if r["config"] == "ncc_fp3") / len(WORKLOADS)
avg_pct_change_mixed   = sum(r["pct_change_W"] for r in system_rows if r["config"] == "mixed") / len(WORKLOADS)

emit("VERDICT:")
emit(f"  NCC hardware power/energy itself is exactly {ncc_total_12k/ncc_total_3k:.2f}x higher at 12000 gates")
emit(f"  ({ncc_total_3k*1e3:.2f} mW -> {ncc_total_12k*1e3:.2f} mW), a deterministic consequence of")
emit(f"  FMA_GATE_COUNT appearing linearly in ncc.cc's area/dynamic/leakage formulas.")
emit()
emit(f"  But NCC hardware is a small fraction of total system power (L1+L2 SRAM dominates):")
emit(f"    ncc_fp3 config: NCC share averages {avg_share_ncc_3k:.3f}% at 3K gates, {avg_share_ncc_12k:.3f}% at 12K gates")
emit(f"    mixed   config: NCC share averages {avg_share_mix_3k:.3f}% at 3K gates, {avg_share_mix_12k:.3f}% at 12K gates")
emit()
emit(f"  Net effect on TOTAL system power (full_total_W):")
emit(f"    ncc_fp3 config: average {avg_pct_change_ncc_fp3:+.3f}% change, 3K -> 12K gates")
emit(f"    mixed   config: average {avg_pct_change_mixed:+.3f}% change, 3K -> 12K gates")
emit()
if max(abs(avg_pct_change_ncc_fp3), abs(avg_pct_change_mixed)) < 5.0:
    emit(f"  => NOT SIGNIFICANT at the system level. Quadrupling the gate-count assumption")
    emit(f"     (3000 -> 12000) changes total system power/energy by well under 5%, because")
    emit(f"     NCC hardware is a small slice of a total dominated by L1/L2 SRAM leakage and")
    emit(f"     dynamic access energy, which do not depend on FMA_GATE_COUNT at all.")
else:
    emit(f"  => Change exceeds a 5% swing in total system power/energy - treat as significant")
    emit(f"     and revisit downstream conclusions that assumed the 3000-gate NCC numbers.")
emit("=" * W)

# ---------------------------------------------------------------------------
# Save outputs
# ---------------------------------------------------------------------------
txt_path = SCRIPT_DIR / "compare_3k_vs_12k.txt"
txt_path.write_text(buf.getvalue())
print(f"\nText output saved to: {txt_path}")

csv_path = SCRIPT_DIR / "compare_3k_vs_12k.csv"
with open(csv_path, "w", newline="") as f:
    fieldnames = ["workload", "config", "full_total_W_3k", "full_total_W_12k", "delta_W",
                  "pct_change_W", "full_total_energy_J_3k", "full_total_energy_J_12k", "pct_change_energy"]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(system_rows)
print(f"CSV  output saved to: {csv_path}")
