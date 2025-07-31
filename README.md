# HBM Bandwidth Test

This repository defines a test example for HBM memory bandwidth, on top of AVED.

## How to build
Building the project requires two steps, building the HLS core and the Vivado project:

```bash
source <path_to_vivado_2024.2>/settings64.sh
cd <project_root>/hw/amd_v80_gen5x8_24.1/src/iprepo/hbm_bandwidth_v1_0
make
```

```bash
source <path_to_vivado_2024.2>/settings64.sh
cd <project_root>/hw/amd_v80_gen5x8_24.1
./build_all.sh
```

## How to run
Follow the instructions for flashing the PDI image to the FPGA and run the software, as described below.

In the `sw/MMIO` directory, two python scripts are present, one that tests the invidual throughput of each core, and one that tests the throughput of all cores at the same time.