#!/usr/bin/env python3
"""
parse_ncc_out.py -- collect the NCC gate-count sweep (Revision_Plan.md Phase 3A, 2026-10-08).

Reads the NCC block that CACTI prints for each run in ncc_runs/g<G>_a<alpha>.txt
(configs/cache_a100_ncc_g<G>_a<alpha>.cfg; 22 nm, 80 units x 32 FP32 FMAs, 1.41 GHz,
routing factor 1.25) and writes ncc_variants.json, one entry per gate count:

  gate_count, nand2_area_um2 (CACTI's own minimum NAND2), routing_factor, area_per_gate_um2,
  unit_area_mm2, total_area_mm2, pct_of_l2 (L2 area from the baseline CACTI .out, 80 slices),
  leak_W (80 units), dyn_W {alpha: W, 80 units}, p_unit_alpha1_W, e_op_J

e_op_J = P_unit(alpha = 1) / f: the energy of one warp-wide NCC operation (all 32 FMAs of
one unit switching for one cycle). Dynamic power is linear in alpha, so dyn_W at any alpha
is alpha * 80 * p_unit_alpha1_W.

Usage: python3 parse_ncc_out.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'ncc_runs'

# L2 area and clock from compute_power.py's constant section (same exec as compute_unified.py)
_ns = {'__file__': str(HERE / 'compute_power.py')}
exec(compile((HERE / 'compute_power.py').read_text().split('\nSTATS_DIR')[0],
             'compute_power_constants', 'exec'), _ns)
L2_TOTAL_MM2 = _ns['L2_AREA_MM2'] * _ns['N_L2_SLICES']
CLOCK_HZ = _ns['CLOCK_HZ']
N_UNITS = 80

FIELDS = {
    'gate_count': r'Gates per FMA:\s+([\d.e+-]+)',
    'nand2_area_um2': r'NAND2 area:\s+([\d.e+-]+)',
    'routing_factor': r'Routing factor:\s+([\d.e+-]+)',
    'area_per_gate_um2': r'Area per gate:\s+([\d.e+-]+)',
    'unit_area_mm2': r'Area per NCC unit:\s+([\d.e+-]+)',
    'total_area_mm2': r'Total NCC area:\s+([\d.e+-]+)',
    'alpha': r'Activity factor:\s+([\d.e+-]+)',
    'dyn_unit_mW': r'Dynamic power/unit:\s+([\d.e+-]+)',
    'dyn_W': r'Total dynamic power:\s+([\d.e+-]+)',
    'leak_W': r'Total leakage power:\s+([\d.e+-]+)',
}


def parse(path):
    block = path.read_text().split('===== NCC (Near-Cache Compute) Results =====')[1]
    out = {}
    for k, pat in FIELDS.items():
        m = re.search(pat, block)
        if not m:
            raise RuntimeError(f'{path}: no {k}')
        out[k] = float(m.group(1))
    return out


def main():
    variants = {}
    for f in sorted(RUNS.glob('g*_a*.txt')):
        r = parse(f)
        key = f'g{int(r["gate_count"])}'
        v = variants.setdefault(key, {
            'gate_count': int(r['gate_count']),
            'nand2_area_um2': r['nand2_area_um2'],
            'routing_factor': r['routing_factor'],
            'area_per_gate_um2': r['area_per_gate_um2'],
            'unit_area_mm2': r['unit_area_mm2'],
            'total_area_mm2': r['total_area_mm2'],
            'pct_of_l2': 100.0 * r['total_area_mm2'] / L2_TOTAL_MM2,
            'leak_W': r['leak_W'],
            'dyn_W': {},
        })
        for k in ('nand2_area_um2', 'total_area_mm2', 'leak_W'):   # alpha must not change these
            assert abs(v[k] - r[k]) <= 1e-9 * max(1.0, abs(v[k])), (f, k)
        v['dyn_W'][f'{r["alpha"]:g}'] = r['dyn_W']
        if r['alpha'] == 1.0:
            v['p_unit_alpha1_W'] = r['dyn_unit_mW'] * 1e-3
            v['e_op_J'] = v['p_unit_alpha1_W'] / CLOCK_HZ
    for key, v in variants.items():   # linear-in-alpha check against the alpha = 1 run
        for a, w in v['dyn_W'].items():
            expect = float(a) * N_UNITS * v['p_unit_alpha1_W']
            assert abs(w - expect) <= 1e-5 * expect, (key, a, w, expect)
    out = {'l2_total_area_mm2': L2_TOTAL_MM2, 'clock_hz': CLOCK_HZ, 'n_units': N_UNITS,
           'variants': dict(sorted(variants.items(), key=lambda kv: kv[1]['gate_count']))}
    (HERE / 'ncc_variants.json').write_text(json.dumps(out, indent=2) + '\n')
    print(f'L2 total area {L2_TOTAL_MM2:.2f} mm^2')
    print(f'{"gates":>6} {"NAND2 um2":>9} {"area mm2":>9} {"% L2":>6} {"leak W":>8} {"P(a=1) W":>9} {"E_op pJ":>8}')
    for v in out['variants'].values():
        print(f'{v["gate_count"]:6d} {v["nand2_area_um2"]:9.6f} {v["total_area_mm2"]:9.4f} {v["pct_of_l2"]:6.3f} '
              f'{v["leak_W"]:8.5f} {N_UNITS * v["p_unit_alpha1_W"]:9.4f} {v["e_op_J"] * 1e12:8.3f}')


if __name__ == '__main__':
    main()
