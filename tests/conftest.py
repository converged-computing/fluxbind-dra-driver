import os
import shutil

import pytest

here = os.path.dirname(os.path.abspath(__file__))
TOPOLOGIES = os.path.join(here, "topologies")


def topology_path(name: str) -> str:
    """
    Return the path to a test hwloc XML topology.
    """
    return os.path.join(TOPOLOGIES, name)


requires_hwloc = pytest.mark.skipif(
    shutil.which("hwloc-calc") is None, reason="hwloc-calc is not installed"
)
