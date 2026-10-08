#include "ncc.h"
#include "parameter.h"
#include "basic_circuit.h"
#include "cacti_interface.h"
#include "component.h"

// FP32 FMA gate-count model (revised 2026-10-08).
//   An FP32 FMA is modeled as p.gate_count NAND2-equivalent gates (GE). One GE is the
//   area of a two-input NAND gate (McKay et al., NISTIR 8114, 2017, Sec. 2.2.1; Kaeslin,
//   Digital Integrated Circuit Design, 2008, Sec. 1.2.1). The gate counts swept
//   (5.5k, 8.3k, 10.1k, 20k) and their published sources are listed in
//   power_analysis/fma_gate_count_sources.md.
//   Area: the NAND2 area comes from CACTI's own layout model (Component::compute_gate_area,
//   the rules CACTI applies to the cache peripheral logic), times p.routing_factor
//   (1.25 = 80% placement utilization, Kaiser et al., SuperFri 6(2), 2019, Sec. 4.1).
//   Replaces the earlier unsourced 0.040 um^2 x 2 routing at 7 nm scaled by F^2.
static const double TXN_PER_GATE      = 4.0;     // transistors per NAND2 gate

NCC_result model_ncc(const NCC_params &p)
{
    NCC_result r;

    const double Vdd      = g_tp.peri_global.Vdd;    // V
    const double clock_hz = p.clock_mhz * 1.0e6;     // Hz

    // -----------------------------------------------------------------------
    // Area
    // Minimum-size NAND2 (same widths as the leakage model below) laid out with
    // CACTI's rules at the configured node; compute_gate_area returns um^2.
    // -----------------------------------------------------------------------
    const double w_n = g_tp.min_w_nmos_;
    const double w_p = g_tp.peri_global.n_to_p_eff_curr_drv_ratio * g_tp.min_w_nmos_;
    Component layout;
    r.nand2_area_um2        = layout.compute_gate_area(NAND, 2, w_p, w_n, g_tp.cell_h_def);
    r.area_per_gate_um2     = r.nand2_area_um2 * p.routing_factor;
    double area_per_fma     = p.gate_count * r.area_per_gate_um2 * 1.0e-6;  // mm^2/FMA
    r.area_per_unit_mm2     = area_per_fma * (double)p.fus_per_unit;
    r.total_area_mm2        = r.area_per_unit_mm2 * (double)p.num_units;

    // -----------------------------------------------------------------------
    // Dynamic power
    // Use CACTI's gate_C() for the actual gate capacitance at the current node.
    // gate_C(width_um, 0) returns F per minimum-width NMOS gate.
    // Each NAND2-equivalent gate has TXN_PER_GATE transistors; model all as
    // minimum-width NMOS to get a conservative (lower-bound) capacitance.
    // P = alpha * C_eff * Vdd^2 * f
    // -----------------------------------------------------------------------
    double C_per_gate_F  = gate_C(g_tp.min_w_nmos_, 0) * TXN_PER_GATE; // F per gate
    double C_per_fma_F   = C_per_gate_F * p.gate_count;
    double C_per_unit_F  = C_per_fma_F * (double)p.fus_per_unit;
    double dyn_W         = p.activity_factor * C_per_unit_F * Vdd * Vdd * clock_hz;
    r.dynamic_power_per_unit_mW = dyn_W * 1.0e3;
    r.total_dynamic_power_W     = dyn_W * (double)p.num_units;

    // -----------------------------------------------------------------------
    // Leakage power
    // Use CACTI's cmos_Isub_leakage() for a minimum-width NAND2 gate, then
    // scale by gate count and supply voltage.
    // -----------------------------------------------------------------------
    double min_n = g_tp.min_w_nmos_;
    double min_p = g_tp.peri_global.n_to_p_eff_curr_drv_ratio * g_tp.min_w_nmos_;
    // Leakage current (A) for one minimum-width NAND2:
    double leak_per_gate_A = cmos_Isub_leakage(min_n, min_p, 2, nand);
    double leak_per_unit_W = leak_per_gate_A * p.gate_count
                             * (double)p.fus_per_unit * Vdd;
    r.leakage_power_per_unit_mW = leak_per_unit_W * 1.0e3;
    r.total_leakage_power_W     = leak_per_unit_W * (double)p.num_units;

    return r;
}
