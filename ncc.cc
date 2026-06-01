#include "ncc.h"
#include "parameter.h"
#include "basic_circuit.h"
#include "cacti_interface.h"

// FP32 FMA gate-count model:
//   An FP32 FMA circuit is approximated as ~3000 NAND2-equivalent gates.
//   Source: published GPU die analysis and standard-cell FP32 multiplier studies.
static const double FMA_GATE_COUNT    = 3000.0;  // NAND2-equiv gates per FP32 FMA
static const double TXN_PER_GATE      = 4.0;     // transistors per NAND2 gate

// Area calibration anchor: TSMC N7 (7 nm, as used on NVIDIA A100).
//   A NAND2 standard cell at 7 nm occupies ~0.040 um^2 with a ~2x routing overhead,
//   giving ~0.080 um^2 = 8e-8 mm^2 per gate.
//   Area scales as F^2 across technology nodes.
static const double REF_F_SZ_UM         = 0.007; // 7 nm reference feature size (um)
static const double REF_AREA_GATE_MM2   = 8.0e-8; // mm^2 per NAND2-equiv gate at 7 nm

NCC_result model_ncc(const NCC_params &p)
{
    NCC_result r;

    const double F_sz_um  = g_ip->F_sz_um;
    const double Vdd      = g_tp.peri_global.Vdd;    // V
    const double clock_hz = p.clock_mhz * 1.0e6;     // Hz

    // -----------------------------------------------------------------------
    // Area
    // Scale NAND2 footprint from 7 nm reference: area proportional to F^2.
    // -----------------------------------------------------------------------
    double area_scale       = (F_sz_um / REF_F_SZ_UM) * (F_sz_um / REF_F_SZ_UM);
    double area_per_gate    = REF_AREA_GATE_MM2 * area_scale;  // mm^2/gate
    double area_per_fma     = FMA_GATE_COUNT * area_per_gate;  // mm^2/FMA
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
    double C_per_fma_F   = C_per_gate_F * FMA_GATE_COUNT;
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
    double leak_per_unit_W = leak_per_gate_A * FMA_GATE_COUNT
                             * (double)p.fus_per_unit * Vdd;
    r.leakage_power_per_unit_mW = leak_per_unit_W * 1.0e3;
    r.total_leakage_power_W     = leak_per_unit_W * (double)p.num_units;

    return r;
}
