#ifndef __NCC_H__
#define __NCC_H__

// NCC (Near-Cache Compute) hardware model for CACTI.
// Models the FP32 FMA datapaths placed at each L2 cache slice.

struct NCC_params {
  unsigned num_units;        // NCC units (one per L2 slice, e.g. 80 for A100)
  unsigned fus_per_unit;     // FP32 FMAs per NCC unit (= warp width, e.g. 32)
  double   clock_mhz;        // NCC clock frequency = L2 clock (e.g. 1410 MHz on A100)
  double   activity_factor;  // average FU switching activity (0.054 from dissertation)
  double   gate_count;       // NAND2-equivalent gates per FP32 FMA (see power_analysis/fma_gate_count_sources.md)
  double   routing_factor;   // layout area / cell area = 1 / placement utilization (1.25 = 80%)
};

struct NCC_result {
  double nand2_area_um2;     // CACTI's minimum-size 2-input NAND at the configured node
  double area_per_gate_um2;  // nand2_area_um2 * routing_factor
  double area_per_unit_mm2;
  double total_area_mm2;
  double dynamic_power_per_unit_mW;
  double total_dynamic_power_W;
  double leakage_power_per_unit_mW;
  double total_leakage_power_W;
};

// Computes NCC area/power estimates using CACTI's g_tp technology parameters.
// g_tp and g_ip must be initialized (init_tech_params called) before invoking.
NCC_result model_ncc(const NCC_params &p);

#endif
