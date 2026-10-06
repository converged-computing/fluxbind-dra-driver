import os
import random
import subprocess

import pytest
from conftest import requires_hwloc, topology_path

from fluxbind_dra import cpuset


@pytest.mark.parametrize(
    "mask,expected",
    [
        ("0x0000000f", [0, 1, 2, 3]),
        ("0x1", [0]),
        ("0x000f0000,0x0000000f", [0, 1, 2, 3, 48, 49, 50, 51]),
        # hwloc writes all-zero 32-bit words as empty
        ("0x80000000,,0x00000001", [0, 95]),
        ("0x80000000,,0x0", [95]),
        ("0xffffffff,0xffffffff,0xffffffff", list(range(96))),
        # taskset (single word) format
        ("0x1000000000001000000", [24, 72]),
        ("0x0", []),
    ],
)
def test_parse_hwloc_mask(mask, expected):
    assert cpuset.parse_hwloc_mask(mask) == expected


@pytest.mark.parametrize("mask", ["", "  ", "0xzz", "0x1ffffffff,0x0", "0xf...f"])
def test_parse_hwloc_mask_rejects_invalid(mask):
    with pytest.raises(ValueError):
        cpuset.parse_hwloc_mask(mask)


@pytest.mark.parametrize(
    "cpus,expected",
    [
        ([], ""),
        ([3], "3"),
        ([0, 1, 2, 3], "0-3"),
        ([3, 1, 2, 0, 0], "0-3"),
        ([0, 48, 1, 49], "0-1,48-49"),
        ([0, 2, 4], "0,2,4"),
        ([0, 1, 5, 6, 7, 95], "0-1,5-7,95"),
    ],
)
def test_format_cpulist(cpus, expected):
    assert cpuset.format_cpulist(cpus) == expected


def _hwloc(xml, *args):
    env = dict(os.environ, HWLOC_XMLFILE=xml)
    return subprocess.run(
        ["hwloc-calc", *args], env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


@requires_hwloc
@pytest.mark.parametrize("xml", ["single-node.xml", "corona.xml"])
def test_parse_matches_hwloc(xml):
    xml = topology_path(xml)
    npus = int(_hwloc(xml, "-N", "pu", "machine:0"))
    rng = random.Random(0)
    for _ in range(25):
        chosen = sorted(rng.sample(range(npus), rng.randint(1, npus)))
        locations = [f"pu:{i}" for i in chosen]
        mask = _hwloc(xml, "--physical-input", *locations)
        assert cpuset.parse_hwloc_mask(mask) == chosen, mask
