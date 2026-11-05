# FP32 FMA gate count, NAND2 area and routing factor: sources

Used by `ncc.cc` (`-ncc_gate_count`, `-ncc_routing_factor`) and `ncc_variants.json`.
Decided with the user on 2026-10-08 (`Revision_Plan.md` Phase 3A).
Cite the **published** versions.

**Status (2026-10-08):** every value below has been verified against the published PDFs in `Research_Papers/`:
- Johnson: Table II, 481.2 µm²; Table III, 591.0 µm².
- FPnew: Table II, p. 779, FP32 "parallel (3,2)"; Fig. 6, p. 781, FP32 40 kGE, 1 GE ≈ 0.199 µm².
- Xu: Table 3, utilization 61.6-71.1%.
- Clark: 7.5-track cells on a 36 nm M2 pitch (270 nm) and 54 nm CPP, consistent with the LEF NAND2xp33 at 4 CPP × 270 nm.
- Kaeslin: §1.2.1 quote.
- Kaiser: §4.1, pp. 64-74.

The earlier "check vs published" notes are resolved.

**Bib keys** (`dissertation_bibliography.bib`, `CACTI:` prefix):

| Key | Source |
|---|---|
| `CACTI:GateEquivalent` | Kaeslin 2008 |
| `CACTI:NISTIR8114` | McKay et al. 2017 |
| `CACTI:FPnew` | Mach et al. 2021 |
| `CACTI:LogArithmetic` | Johnson 2020 |
| `CACTI:ASAP7` | Clark et al. 2016 |
| `CACTI:ASAP7_StdCell` | Xu et al. 2017 |
| `CACTI:RISCV_FMA` | Kaiser et al. 2019 |
| `CACTI` (existing) | CACTI 7, for CACTI's own NAND2 area |

## Gate-equivalent definition
- **McKay, Bassham, Sönmez Turan, Mouha**, "Report on Lightweight Cryptography," NISTIR 8114, NIST, March 2017, §2.2.1, p. 4. DOI 10.6028/NIST.IR.8114.
  - Quote: "For ASICs, one GE is equivalent to the area that is required by the two-input NAND gate. The area in GEs is obtained by dividing the area in µm2 by the area of the NAND gate."
  - PDF: `Research_Papers/McKay et al. - 2017 - Report on Lightweight Cryptography (NISTIR 8114).pdf`
- **Kaeslin**, *Digital Integrated Circuit Design: From VLSI Architectures to CMOS Fabrication*, Cambridge University Press, 2008, §1.2.1, p. 4. DOI 10.1017/CBO9780511805172.
  - Quote: "One gate equivalent (GE) stands for a two-input nand gate and corresponds to four MOSFETs in static CMOS; a flip-flop takes roughly 7 GEs."
  - Paywalled; the user provides it.

## Gate counts swept

| Gate count (GE) | Source (published version) | Raw figure | NAND2 used | Notes |
|---|---|---|---|---|
| 5,500 | Johnson, "Efficient, arbitrarily high precision hardware logarithmic arithmetic for linear algebra," ARITH 2020, pp. 25-32, DOI 10.1109/ARITH48897.2020.00013, Table II | float32 FMA 481.2 µm², commercial 7 nm, SVT, HLS + Design Compiler, fully pipelined | ASAP7 NAND2x1 0.324 × 0.27 µm = 0.0875 µm² (Clark et al. 2016) | 481.2 / 0.0875 = 5,501. Check vs published. |
| 8,300 | same as above | 481.2 µm² | ASAP7 NAND2xp33 0.216 × 0.27 µm = 0.0583 µm² | 481.2 / 0.0583 = 8,251. Smallest NAND2 cell, so this is the standard GE conversion. |
| 10,100 | same, Table III | float32 FMA inside a 128-length inner-product unit, 591.0 µm² | ASAP7 NAND2xp33 0.0583 µm² | 591.0 / 0.0583 = 10,134 |
| 20,000 | Mach, Schuiki, Zaruba, Benini, "FPnew," IEEE TVLSI 29(4):774-787, 2021, DOI 10.1109/TVLSI.2020.3044752, Table II and Fig. 6 | FP32 FMA slice in the Ariane FPU: 40 kGE for 2 lanes, 3 pipeline stages, GF 22FDX, 1 GE ≈ 0.199 µm² | reported directly in GE | 40 kGE / 2 = 20.0k. Check vs published. |

**ASAP7 cell sizes:**
- Source: Clark et al., "ASAP7: A 7-nm finFET predictive process design kit," Microelectronics Journal 53:105-115, 2016, DOI 10.1016/j.mejo.2016.04.006.
- Cell dimensions read from the 1× LEF `asap7sc7p5t_28_R_1x_220121a.lef` (OpenROAD-flow-scripts `platforms/asap7`).
- Paywalled; the user provides it.

**Not used:**
- **Weak conversions:** Galal 2012 (TSMC 45 nm µm² ÷ Nangate NAND2, two different libraries), Brunie ARITH 2017 (28 nm, scaled NAND2), FPMax (preprint).
- **Not convertible:** Zhao arXiv 2026 (cell counts), PERCIVAL (a whole FPU).
- **Lower bound only:** Blumenfeld ICLR 2024 (analytical model, no registers or rounding).

Details are in `Revision_Plan.md` §3A item 2.

## NAND2 area: CACTI's own layout model
- `Component::compute_gate_area(NAND, 2, w_p, w_n, cell_h_def)` in `component.cc`, with:
  - w_n = `min_w_nmos_` = 1.5F;
  - w_p = n2p × w_n, where n2p = 2 for the 22 nm high-performance flavor (`tech_params/22nm.dat`, `-n2p_drv_rt`);
  - the layout rules in `parameter.cc:1187-1197` (5F P/N gap, 2F power rail, poly contact F, contact spacing F, poly spacing 1.5F).
- Width: 9.5F (2-input series stack). Height: w_n + w_p + 5F + 4F = 13.5F.
- At F = 22 nm: **0.062073 µm²** (printed by `cacti`; hand calculation 0.0621).
- These are the same rules CACTI applies to the cache peripheral logic, so the NCC-to-L2 area ratio is on one basis.
- Cite as CACTI 7: Balasubramonian et al., ACM TACO 2017 (bib key `CACTI`).
- For comparison: a real 22 nm library gate equivalent is 0.199 µm² (GF 22FDX, FPnew/Ara). CACTI's rule-based cell is about 3.2× smaller.

## Routing (placement utilization) factor
- **Used: 1.25×** (80% utilization). Kaiser, Kosnac, Brüning, "Development of a RISC-V-Conform Fused Multiply-Add Floating-Point Unit," Supercomputing Frontiers and Innovations 6(2):64-74, 2019, §4.1, DOI 10.14529/jsfi190205.
  - Quote: "The length was adjusted to yield a utilization of 80%."
  - It is an FMA unit in GF 22FDX.
  - PDF: `Research_Papers/Kaiser et al. - 2019 - Development of a RISC-V-Conform Fused Multiply-Add Floating-Point Unit.pdf`
- **Range reference:** Xu, Shah, Evans, Sinha, Cline, Yeric, "Standard Cell Library Design and Optimization Methodology for ASAP7 PDK," ICCAD 2017, pp. 999-1004, DOI 10.1109/ICCAD.2017.8203890, Table 3.
  - An Arm Cortex-M0 placed and routed in ASAP7: utilization 61.6-71.1% (1.41-1.62×).
  - Paywalled; the user provides it.
- Replaced: the unsourced 2× (50% utilization) in the original `ncc.cc`.

## Results (22 nm, 80 units × 32 FMAs, 1.41 GHz, 1.25×; from `ncc_variants.json`, L2 = 167.69 mm²)

| Gates | Area (mm²) | % of L2 | Leakage (W) | P(α=1), 80 units (W) | E_op (pJ) |
|---|---|---|---|---|---|
| 5,500 | 1.0925 | 0.651 | 0.28832 | 0.9600 | 8.511 |
| 8,300 | 1.6487 | 0.983 | 0.43510 | 1.4487 | 12.843 |
| 10,100 | 2.0062 | 1.196 | 0.52946 | 1.7629 | 15.629 |
| 20,000 | 3.9727 | 2.369 | 1.04844 | 3.4909 | 30.948 |

Reference rows, not in the sweep:
- 3,000 gates (legacy count): 0.5959 mm².
- 12,000 gates: 2.3836 mm², 18.569 pJ.

The old dissertation value, 6.07 mm² / 3.62% at 3,000 gates, used the unsourced 0.040 µm² × 2 routing at 7 nm scaled by (22/7)².

## Power gating of the NCC units (main case, user 2026-10-09)
Kernel-level gating, implemented in `research_figures/dissertation_figures/unified_eval/warm_safe_eval.py` (`gated` mode). The NCC units are powered only while an offloaded kernel runs.

| Parameter | Value used | Source (published versions in `Research_Papers/`) |
|---|---|---|
| Wake-up delay | 3 cycles per offloaded launch | `CACTI:WarpedGates`: Abdel-Majeed, Wong, Annavaram, MICRO 2013, pp. 111-122, DOI 10.1145/2540708.2540719, §2.2: "estimated the wakeup delay to be around 3 cycles and break-even time to be between 9 and 24 cycles [13]" |
| Break-even time | 24 cycles × NCC leakage, per offloaded launch | top of the 9-24 range (`CACTI:WarpedGates` §2.2). `CACTI:PowerGatingEU`: Hu et al., ISLPED 2004, pp. 32-37, DOI 10.1145/1013235.1013249, p. 34: N_break-even ≈ 10 (§2.1); T_overhead = T_wakeup + T_breakeven of 9/14/19/24 explored (§2.2) |
| Leakage while gated | 0 | `CACTI:PowerGatingEU` §2.1 assumes no leakage through the header device; `CACTI:WarpedGates` §2.2: "a very small leakage current" |
