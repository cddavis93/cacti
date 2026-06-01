#ifndef __NCC_H__
#define __NCC_H__

// NCC (Near-Cache Compute) hardware model for CACTI.
// Models the FP32 FMA datapaths placed at each L2 cache slice.

struct NCC_params {
  unsigned num_units;        // NCC units (one per L2 slice, e.g. 80 for A100)
  unsigned fus_per_unit;     // FP32 FMAs per NCC unit (= warp width, e.g. 32)
  double   clock_mhz;        // NCC clock frequency = L2 clock (e.g. 1410 MHz on A100)
  double   activity_factor;  // average FU switching activity (0.054 from dissertation)
};

struct NCC_result {
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
