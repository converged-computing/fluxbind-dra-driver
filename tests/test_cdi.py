import json

from fluxbind_dra.devices import CDIManager


def read(path):
    with open(path) as f:
        return json.load(f)


def test_initializes_spec(tmp_path):
    path = tmp_path / "cdi" / "fluxbind.json"
    CDIManager(str(path))
    spec = read(path)
    assert spec["kind"] == "fluxbind/shape"
    assert spec["devices"] == []


def test_add_device_injects_cpus_and_mask(tmp_path):
    path = tmp_path / "fluxbind.json"
    cdi = CDIManager(str(path))
    name = cdi.add_device("uid-1", "0-1,48-49", "0x00030000,0x00000003")
    assert name == "claim-uid-1"
    (device,) = read(path)["devices"]
    assert device["containerEdits"]["env"] == [
        "FLUXBIND_CPUS=0-1,48-49",
        "FLUXBIND_CPUSET=0x00030000,0x00000003",
    ]


def test_add_device_is_idempotent(tmp_path):
    path = tmp_path / "fluxbind.json"
    cdi = CDIManager(str(path))
    cdi.add_device("uid-1", "0", "0x1")
    cdi.add_device("uid-1", "1", "0x2")
    devices = read(path)["devices"]
    assert len(devices) == 1
    assert "FLUXBIND_CPUS=1" in devices[0]["containerEdits"]["env"]


def test_remove_device(tmp_path):
    path = tmp_path / "fluxbind.json"
    cdi = CDIManager(str(path))
    cdi.add_device("uid-1", "0", "0x1")
    cdi.add_device("uid-2", "1", "0x2")
    cdi.remove_device("uid-1")
    cdi.remove_device("uid-missing")
    assert [d["name"] for d in read(path)["devices"]] == ["claim-uid-2"]


def test_existing_spec_is_preserved(tmp_path):
    path = tmp_path / "fluxbind.json"
    CDIManager(str(path)).add_device("uid-1", "0", "0x1")
    CDIManager(str(path))
    assert len(read(path)["devices"]) == 1
