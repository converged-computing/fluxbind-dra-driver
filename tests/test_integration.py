import json

import pytest
from conftest import requires_hwloc, topology_path

from fluxbind_dra import server
from fluxbind_dra.devices import CDIManager
from fluxbind_dra.proto.dra import dra_pb2

fluxbind_manager = pytest.importorskip("fluxbind.manager")


@pytest.fixture
def servicer(tmp_path, monkeypatch, request):
    xml = topology_path(request.param)
    monkeypatch.setenv("HWLOC_XMLFILE", xml)

    # fluxbind sizes its thread pool as cpu_count() // 2, which is 0 on 1-CPU hosts.
    import fluxbind.graph.worker as worker

    monkeypatch.setattr(worker.multiprocessing, "cpu_count", lambda: 4)

    servicer = server.DraPluginServicer(CDIManager(str(tmp_path / "fluxbind.json")))
    servicer.manager = fluxbind_manager.NodeResourceManager(
        str(tmp_path / "state.json"), xml_file=xml
    )
    servicer.prepared = True
    return servicer


def prepare(servicer, monkeypatch, uid, shape):
    monkeypatch.setattr(servicer, "get_shape_from_claim", lambda claim: shape)
    return servicer.prepare_claim(dra_pb2.Claim(namespace="default", uid=uid, name=uid))


def cpus_for(servicer, uid):
    with open(servicer.cdi_manager.spec_path) as f:
        (env,) = [
            d["containerEdits"]["env"]
            for d in json.load(f)["devices"]
            if d["name"] == f"claim-{uid}"
        ]
    return next(e.split("=", 1)[1] for e in env if e.startswith("FLUXBIND_CPUS="))


CORES = lambda n: {"resources": [{"type": "core", "count": n}]}  # noqa: E731


@requires_hwloc
@pytest.mark.parametrize(
    "servicer,count,expected",
    [
        ("single-node.xml", 4, "0-7"),
        # corona SMT siblings are os indices N and N+48
        ("corona.xml", 4, "0-3,48-51"),
        ("corona.xml", 48, "0-95"),
    ],
    indirect=["servicer"],
)
def test_core_claim_cpulist(servicer, monkeypatch, count, expected):
    resp = prepare(servicer, monkeypatch, "a", CORES(count))
    assert resp.error == ""
    assert cpus_for(servicer, "a") == expected


@requires_hwloc
@pytest.mark.parametrize("servicer", ["corona.xml"], indirect=True)
def test_second_claim_gets_disjoint_cpus(servicer, monkeypatch):
    prepare(servicer, monkeypatch, "a", CORES(4))
    prepare(servicer, monkeypatch, "b", CORES(4))
    assert cpus_for(servicer, "a") == "0-3,48-51"
    assert cpus_for(servicer, "b") == "4-7,52-55"


@requires_hwloc
@pytest.mark.parametrize("servicer", ["single-node.xml"], indirect=True)
def test_exhausted_node_reports_error(servicer, monkeypatch):
    assert prepare(servicer, monkeypatch, "a", CORES(8)).error == ""
    assert "Could not allocate" in prepare(servicer, monkeypatch, "b", CORES(1)).error
