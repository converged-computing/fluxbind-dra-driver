import json
import logging

import pytest

from fluxbind_dra import server
from fluxbind_dra.devices import CDIManager
from fluxbind_dra.proto.dra import dra_pb2


class FakeManager:
    """
    Records reservations and returns a fixed binding per claim uid.
    """

    def __init__(self, bindings):
        self.bindings = bindings
        self.released = []

    def create_reservation(self, uid, shape):
        return self.bindings.get(uid)

    def release_reservation(self, uid):
        self.released.append(uid)
        return True


@pytest.fixture
def make_servicer(tmp_path, monkeypatch):
    def _make(bindings, shapes=None):
        shapes = shapes or {}
        cdi = CDIManager(str(tmp_path / "fluxbind.json"))
        servicer = server.DraPluginServicer(cdi)
        servicer.manager = FakeManager(bindings)
        servicer.prepared = True
        monkeypatch.setattr(
            servicer,
            "get_shape_from_claim",
            lambda claim: shapes.get(
                claim.uid, {"resources": [{"type": "core", "count": 1}]}
            ),
        )
        return servicer

    return _make


def claim(uid):
    return dra_pb2.Claim(namespace="default", uid=uid, name=f"claim-{uid}")


def cdi_env(servicer):
    with open(servicer.cdi_manager.spec_path) as f:
        return {d["name"]: d["containerEdits"]["env"] for d in json.load(f)["devices"]}


def test_prepare_claim_multiword_mask(make_servicer):
    servicer = make_servicer({"a": "0x00030000,0x00000003;NONE"})
    resp = servicer.prepare_claim(claim("a"))
    assert resp.error == ""
    assert list(resp.devices[0].cdi_device_ids) == ["fluxbind/shape=claim-a"]
    assert "FLUXBIND_CPUS=0-1,48-49" in cdi_env(servicer)["claim-a"]


def test_prepare_claim_with_gpus(make_servicer):
    servicer = make_servicer({"a": "0x3;0,1"})
    resp = servicer.prepare_claim(claim("a"))
    assert list(resp.devices[0].cdi_device_ids) == [
        "fluxbind/shape=claim-a",
        "nvidia.com/gpu=0,1",
    ]


def test_prepare_claim_allocation_failure(make_servicer):
    servicer = make_servicer({})
    resp = servicer.prepare_claim(claim("a"))
    assert "Could not allocate" in resp.error
    assert cdi_env(servicer) == {}


@pytest.mark.parametrize("mask", ["0x0", "0xnothex"])
def test_prepare_claim_invalid_binding_releases(make_servicer, mask):
    servicer = make_servicer({"a": f"{mask};NONE"})
    resp = servicer.prepare_claim(claim("a"))
    assert "Invalid binding" in resp.error
    assert servicer.manager.released == ["a"]
    assert cdi_env(servicer) == {}


def test_prepare_claim_shape_lookup_failure(make_servicer, monkeypatch):
    servicer = make_servicer({"a": "0x1;NONE"})

    def boom(claim):
        raise KeyError("config")

    monkeypatch.setattr(servicer, "get_shape_from_claim", boom)
    resp = servicer.prepare_claim(claim("a"))
    assert "Failed to get shape" in resp.error


def test_node_prepare_reports_per_claim(make_servicer):
    servicer = make_servicer({"ok": "0x1;NONE"})
    request = dra_pb2.NodePrepareResourcesRequest(claims=[claim("bad"), claim("ok")])
    resp = servicer.NodePrepareResources(request, context=None)
    assert set(resp.claims) == {"bad", "ok"}
    assert resp.claims["bad"].error
    assert resp.claims["ok"].error == ""
    assert "FLUXBIND_CPUS=0" in cdi_env(servicer)["claim-ok"]


def test_node_unprepare(make_servicer):
    servicer = make_servicer({"a": "0x1;NONE"})
    servicer.prepare_claim(claim("a"))
    request = dra_pb2.NodeUnprepareResourcesRequest(claims=[claim("a")])
    resp = servicer.NodeUnprepareResources(request, context=None)
    assert set(resp.claims) == {"a"}
    assert servicer.manager.released == ["a"]
    assert cdi_env(servicer) == {}


def test_warn_unsupported_shape_keys(caplog):
    shape = {
        "resources": [
            {"type": "core", "count": 4, "reverse": True, "pattern": "scatter"}
        ],
        "options": {"bind": "pu"},
    }
    with caplog.at_level(logging.WARNING):
        ignored = server.warn_unsupported_shape_keys("a", shape)
    assert sorted(ignored) == ["bind", "pattern", "reverse"]
    assert "not yet supported" in caplog.text


def test_supported_shape_has_no_warning(caplog):
    shape = {"resources": [{"type": "core", "count": 4}]}
    with caplog.at_level(logging.WARNING):
        assert server.warn_unsupported_shape_keys("a", shape) == []
    assert caplog.text == ""
