import os
import mmap
import struct
import subprocess
import time
import threading
import csv
import argparse

BAR_INDEX = 0
BAR_SIZE = 128 * 1024 * 1024
ITERATIONS = 1
CORES = list(range(64))

MMIO_OFFSETS = {
    0:  0x000000,  1:  0x010000,  2:  0x0C0000,  3:  0x170000,
    4:  0x220000,  5:  0x2D0000,  6:  0x380000,  7:  0x3D0000,
    8:  0x3E0000,  9:  0x3F0000, 10: 0x020000, 11: 0x030000,
    12: 0x040000, 13: 0x050000, 14: 0x060000, 15: 0x070000,
    16: 0x080000, 17: 0x090000, 18: 0x0A0000, 19: 0x0B0000,
    20: 0x0D0000, 21: 0x0E0000, 22: 0x0F0000, 23: 0x100000,
    24: 0x110000, 25: 0x120000, 26: 0x130000, 27: 0x140000,
    28: 0x150000, 29: 0x160000, 30: 0x180000, 31: 0x190000,
    32: 0x1A0000, 33: 0x1B0000, 34: 0x1C0000, 35: 0x1D0000,
    36: 0x1E0000, 37: 0x1F0000, 38: 0x200000, 39: 0x210000,
    40: 0x230000, 41: 0x240000, 42: 0x250000, 43: 0x260000,
    44: 0x270000, 45: 0x280000, 46: 0x290000, 47: 0x2A0000,
    48: 0x2B0000, 49: 0x2C0000, 50: 0x2E0000, 51: 0x2F0000,
    52: 0x300000, 53: 0x310000, 54: 0x320000, 55: 0x330000,
    56: 0x340000, 57: 0x350000, 58: 0x360000, 59: 0x370000,
    60: 0x390000, 61: 0x3A0000, 62: 0x3B0000, 63: 0x3C0000,
}

REG_AP_CTRL     = 0x00
REG_HBM_PTR_L   = 0x10
REG_HBM_PTR_H   = 0x14

LENGTH_BYTES = 512 * 1024 * 1024  # 512MB per iteration
TIMEOUT = 10  # seconds

def parse_args():
    parser = argparse.ArgumentParser(
        description="HBM bandwidth benchmark over PCIe BAR MMIO"
    )
    parser.add_argument(
        "--pci-addr",
        "-p",
        default="0000:1b:00.2",
        help="PCI address of the device (domain:bus:dev.func), e.g. 0000:1b:00.2",
    )
    return parser.parse_args()

def read32(mem, offset):
    mem.seek(offset)
    return struct.unpack("<I", mem.read(4))[0]

def write32(mem, offset, value):
    mem.seek(offset)
    mem.write(struct.pack("<I", value))

def prepare_core(mem, core_index, hbm_addr):
    base = MMIO_OFFSETS[core_index]
    print(f"Preparing Core {core_index}, HBM Address: {hex(hbm_addr)}")
    write32(mem, base + REG_HBM_PTR_L, hbm_addr & 0xFFFFFFFF)
    write32(mem, base + REG_HBM_PTR_H, (hbm_addr >> 32) & 0xFFFFFFFF)

def start_all_cores(mem, core_indices):
    for core_index in core_indices:
        base = MMIO_OFFSETS[core_index]
        mem.seek(base + REG_AP_CTRL)
        mem.write(struct.pack("<I", 0x1))
    mem.flush()

def wait_for_done(mem, core_index, timeout=TIMEOUT):
    base = MMIO_OFFSETS[core_index]
    elapsed = 0
    interval = 0.001

    if read32(mem, base + REG_AP_CTRL) == 0xFFFFFFFF:
        print(f"[!] Core {core_index} BAR region not mapped.")
        return False

    while elapsed < timeout:
        ctrl = read32(mem, base + REG_AP_CTRL)
        if ctrl == 0x04:
            return True
        time.sleep(interval)
        elapsed += interval

    print(f"[!] Timeout waiting for core {core_index}")
    return False

def main(PCI_ADDR: str):
    bar_path = f"/sys/bus/pci/devices/{PCI_ADDR}/resource{BAR_INDEX}"
    fd = os.open(bar_path, os.O_RDWR | os.O_SYNC)
    mem = mmap.mmap(fd, BAR_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
    os.close(fd)

    print("[+] Preparing cores:", CORES)
    for core_index in CORES:
        hbm_addr = 0x4000000000 + core_index * 0x20000000
        prepare_core(mem, core_index, hbm_addr)

    print("[+] Starting cores")
    t0 = time.perf_counter_ns()
    start_all_cores(mem, CORES)

    threads = []
    results = {}

    def wait_and_record(core_index):
        t_start = time.perf_counter_ns()
        success = wait_for_done(mem, core_index)
        t_end = time.perf_counter_ns()
        duration_ms = (t_end - t_start) / 1e6
        results[core_index] = (success, duration_ms)

    for core_index in CORES:
        t = threading.Thread(target=wait_and_record, args=(core_index,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()
        t1 = time.perf_counter_ns()

    mem.close()

    failed = [c for c, ok in results.items() if not ok]
    if failed:
        print(f"[!] Cores failed: {failed}")
    else:
        total_bytes = len(CORES) * ITERATIONS * LENGTH_BYTES
        duration_sec = (t1 - t0) / 1e9
        throughput_gbps = total_bytes / duration_sec / (1024 ** 3)

        print(f"[✓] All cores done in {duration_sec * 1000:.3f} ms ({throughput_gbps:.2f} GB/s)")
        with open("results.csv", "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["core", "success", "duration_ms"])
            for core, (success, duration) in sorted(results.items()):
                writer.writerow([core, int(success), f"{duration:.3f}"])

if __name__ == "__main__":
    args = parse_args()
    main(args.pci_addr)
