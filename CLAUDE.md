# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is CACTI

CACTI 7.0 is an analytical C++ tool that models caches, memories, 3D stacking, and off-chip I/O. Given a configuration, it calculates access time, power (dynamic + leakage), cycle time, and area. It originated at HP Labs and has gone through seven major revisions.

Version 7 adds three major capabilities on top of 6.5:
- **IO model** (`io.cc`, `extio.cc`, `extio_technology.cc`, `memorybus.cc`) — off-chip DDR bus latency/energy
- **3D DRAM model** (`TSV.cc`) — die-stacked DRAM with TSV modeling
- **Power gating** (`powergating.cc`) — sleep transistor models for SRAM arrays, wordlines, and column lines

## Build

```bash
make          # debug build (single-threaded, -O0)
make opt      # optimized build (multithreaded, default NTHREADS=8)
make clean    # clean both builds
```

Artifacts land in `obj_dbg/` or `obj_opt/`, then the `cacti` binary is copied to the repo root.

The build uses two makefiles: `makefile` (top-level dispatcher) and `cacti.mk` (actual rules). Compiler is `g++ -m64`.

## Running

Config-file mode (preferred):
```bash
./cacti -infile configs/cache_a100_ncc.cfg
```

Command-line mode (52, 55, or 64 positional args — see README for the full list):
```bash
./cacti <cache_size> <line_size> <associativity> ... <ecc>
```

Regression tests are listed in `regression.test`; run them manually by executing each `./cacti -infile ...` line.

## Configuration files

`cache_a100_ncc.cfg` is the primary NCC config (A100 L2 slice + NCC enabled). Lines beginning with `//` are commented out. Key parameters:
- `-size (bytes)` — cache/memory size
- `-technology (u)` — process node in microns (16nm–180nm; data in `tech_params/`)
- `-cache type "cache"|"ram"|"main memory"` — selects tag array presence and access granularity
- `-Cache model (NUCA, UCA)` — UCA = uniform cache access, NUCA = non-uniform (banked)
- `-design objective (weight delay, dynamic power, leakage power, cycle time, area)` / `-deviate` — optimizer weights
- `-Optimize ED or ED^2` — disables weight/deviate in favor of energy-delay product minimization

Additional example configs: `ddr3.cfg`, `dram.cfg`, `lpddr.cfg`, `2DDRAM_*.cfg`, `3DDRAM_*.cfg`, and files under `sample_config_files/`.

## Architecture

### Computation flow

`cacti_interface()` (`cacti_interface.cc`) is the main entry point for both the CLI and library consumers (e.g., McPAT). It:
1. Parses `InputParameter` from a cfg file or from arguments
2. Calls `Ucache.cc` which sweeps the design space across array configurations (Ndwl × Ndbl × Nspd × Ndcm × Ndsam)
3. Each candidate is evaluated through a hierarchy: `Bank` → `Mat` → `Subarray`, computing delay and power bottom-up
4. Returns the best `uca_org_t` (or `nuca_org_t` for NUCA) according to the configured objective

### Key class hierarchy

| File | Role |
|------|------|
| `cacti_interface.h` | Public API types: `InputParameter`, `uca_org_t`, `mem_array`, `powerDef`, `powerComponents` |
| `Ucache.cc/.h` | Top-level UCA optimizer; sweeps configurations, calls `solve()` |
| `nuca.cc/.h` | NUCA optimizer; adds network/router modeling on top of UCA banks |
| `bank.cc/.h` | Bank-level area/power/delay aggregation |
| `mat.cc/.h` | Mat-level model (a mat = group of subarrays sharing decoders) |
| `subarray.cc/.h` | Subarray-level bitcell array and sense amp model |
| `htree2.cc/.h` | H-tree interconnect model for address/data distribution |
| `decoder.cc/.h` | Row/column decoder delay and power |
| `wire.cc/.h` | Wire delay, power, area for different wire types |
| `technology.cc` | Loads technology parameters from `tech_params/*.dat` into `g_tp` global |
| `parameter.cc/.h` | Global technology parameter struct (`TechnologyParameter g_tp`) |
| `basic_circuit.cc/.h` | Transistor-level primitives (gate cap, drain cap, driver sizing) |
| `area.cc/.h` | Area calculation helpers |
| `component.cc/.h` | Base class providing `delay_power_area` interface |

### IO and 3D-specific modules

| File | Role |
|------|------|
| `io.cc/.h` | Off-chip I/O latency/energy model entry point |
| `extio.cc/.h` | External I/O circuit models (PHY, termination) |
| `extio_technology.cc/.h` | Per-DRAM-type technology parameters (DDR3/DDR4/LPDDR2/WideIO/Serial) |
| `memorybus.cc/.h` | Memory bus (BoB/DIMM) capacity and bandwidth model |
| `memcad.cc/.h` | MemCAD interconnect explorer |
| `memcad_parameters.cc/.h` | MemCAD parameter parsing |
| `TSV.cc/.h` | Through-silicon via (TSV) area, delay, power for 3D stacking |
| `powergating.cc/.h` | Sleep transistor sizing and wakeup latency/energy |
| `crossbar.cc/.h` | Crossbar switch model (used in NUCA networks) |
| `arbiter.cc/.h` | Arbiter delay/power |
| `router.cc/.h` | Router model (used in NUCA) |

### Global state

`g_ip` (`InputParameter`) and `g_tp` (`TechnologyParameter`) are the two key globals. `technology.cc` populates `g_tp` by interpolating from the `.dat` files in `tech_params/` based on `g_ip.F_sz_nm`. All downstream calculations read from these globals.

### McPAT integration

`cacti_interface.h` explicitly marks two overloads as "McPAT's plain interface, please keep": `cacti_interface(InputParameter*)` and `init_interface(InputParameter*)`. These are called directly by McPAT and must not have their signatures changed.
