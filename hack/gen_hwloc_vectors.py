#!/usr/bin/env python3
"""
Regenerate the golden hwloc bitmask vectors used by the NRI plugin tests.

The NRI plugin has to parse hwloc's cpuset bitmask format. That format is not
obvious: fields are 32 bits wide, comma separated, printed MOST SIGNIFICANT FIRST,
and runs of all-zero fields are compressed to empty fields (one empty field per
zero group). Rather than hand-write test vectors and hope, we ask hwloc itself.

Usage:
    hack/gen_hwloc_vectors.py > cmd/fluxbind-nri/testdata/hwloc-masks.tsv

Requires: hwloc (lstopo-no-graphics, hwloc-calc).
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# A synthetic 512-PU node: 2 packages x 2 NUMA x 8 L3 x 8 cores x 2 PUs.
# Large enough to exercise every interesting field boundary.
SYNTHETIC_TOPOLOGY = "pack:2 numa:2 l3:8 core:8 pu:2"
TOTAL_PUS = 512

# (name, list of PU indices). Chosen to cover field boundaries and the CPU 63/64
# boundary that the original 64-bit parser could not represent.
CASES = [
    ("single cpu 0", [0]),
    ("low group", [0, 1, 2, 3]),
    ("last bit of group 0", [31]),
    ("first bit of group 1", [32]),
    ("straddles group 0 and 1", [31, 32]),
    ("last bit of the old 64 bit limit", [63]),
    ("first cpu past the old 64 bit limit", [64]),
    ("straddles the old 64 bit limit", [63, 64]),
    ("four cores on the second socket", [64, 65, 66, 67]),
    ("high cpu with compressed zero groups", [200]),
    ("first and last cpu of a 512 pu node", [0, 511]),
    ("highest cpu on the node", [511]),
    ("sparse across sockets", [5, 137, 266, 398]),
    ("one cpu per group", [0, 32, 64, 96, 128, 160, 192, 224]),
    ("contiguous span crossing groups", list(range(60, 70))),
    ("entire node", list(range(TOTAL_PUS))),
]


def require(tool: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"error: {tool} not found on PATH; install hwloc first")


def build_topology(path: Path) -> None:
    xml = subprocess.run(
        ["lstopo-no-graphics", "--input", SYNTHETIC_TOPOLOGY, "--output-format", "xml"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    path.write_text(xml)


def hwloc_mask(xml: Path, pus: list[int]) -> str:
    args = [f"pu:{pu}" for pu in sorted(pus)]
    return subprocess.run(
        ["hwloc-calc", "--input", str(xml), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def as_cpu_list(pus: list[int]) -> str:
    """Render sorted PU indices as a compact cpuset-style list, e.g. '0-3,64'."""
    out, pus = [], sorted(set(pus))
    start = prev = pus[0]
    for cpu in pus[1:]:
        if cpu == prev + 1:
            prev = cpu
            continue
        out.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = cpu
    out.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ",".join(out)


def main() -> None:
    require("lstopo-no-graphics")
    require("hwloc-calc")

    print("# Golden hwloc cpuset bitmask vectors. DO NOT EDIT BY HAND.")
    print("# Regenerate with: hack/gen_hwloc_vectors.py > cmd/fluxbind-nri/testdata/hwloc-masks.tsv")
    print(f"# Synthetic topology: {SYNTHETIC_TOPOLOGY} ({TOTAL_PUS} PUs)")
    print("# Columns: name <TAB> hwloc mask <TAB> expected cpu list")

    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "topology.xml"
        build_topology(xml)
        for name, pus in CASES:
            print(f"{name}\t{hwloc_mask(xml, pus)}\t{as_cpu_list(pus)}")


if __name__ == "__main__":
    main()
