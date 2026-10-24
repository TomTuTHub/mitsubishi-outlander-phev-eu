"""Offline tests v1.1.0b4: Tuerschloss unbekannt, Option "Auto aufwecken", jp_2 -> jp_1, SSL-Kontext.

Home Assistant ist lokal nicht installierbar (Python 3.11): minimale Stubs genuegen
fuer lock.py, binary_sensor.py und __init__.py. Keine Netzwerkzugriffe.
"""
import asyncio
import dataclasses
import json
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
if "mitsubishi_outlander_phev_eu" not in sys.modules:
    _stub = types.ModuleType("mitsubishi_outlander_phev_eu")
    _stub.__path__ = [str(_PKG)]
    sys.modules["mitsubishi_outlander_phev_eu"] = _stub


@dataclasses.dataclass
class _Desc:
    key: str = ""
    translation_key: str = None
    device_class: str = None
    icon: str = None
    entity_category: str = None
    entity_registry_enabled_default: bool = True


def _install_ha_stubs():
    names = {
        "homeassistant": {},
        "homeassistant.components": {},
        "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
        "homeassistant.components.lock": {"LockEntity": type("LockEntity", (), {})},
        "homeassistant.components.binary_sensor": {
            "BinarySensorDeviceClass": SimpleNamespace(
                **{n: n for n in ("LOCK", "DOOR", "WINDOW", "RUNNING", "PLUG",
                                  "BATTERY_CHARGING", "PROBLEM", "SAFETY", "LIGHT",
                                  "CONNECTIVITY", "OPENING", "MOVING", "POWER")}),
            "BinarySensorEntity": type("BinarySensorEntity", (), {}),
            "BinarySensorEntityDescription": _Desc,
        },
        "homeassistant.config_entries": {"ConfigEntry": object},
        "homeassistant.const": {"Platform": SimpleNamespace(
            SENSOR="sensor", BINARY_SENSOR="binary_sensor", LOCK="lock", BUTTON="button",
            SWITCH="switch", CLIMATE="climate", DEVICE_TRACKER="device_tracker",
            SELECT="select", TIME="time", NUMBER="number"),
            "EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic", CONFIG="config")},
        "homeassistant.core": {"HomeAssistant": object},
        "homeassistant.exceptions": {
            "ConfigEntryAuthFailed": type("ConfigEntryAuthFailed", (Exception,), {}),
            "ConfigEntryNotReady": type("ConfigEntryNotReady", (Exception,), {}),
            "HomeAssistantError": type("HomeAssistantError", (Exception,), {})},
        "homeassistant.helpers": {},
        "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
        "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": object},
        "homeassistant.helpers.update_coordinator": {
            "CoordinatorEntity": type("CoordinatorEntity", (), {
                "__init__": lambda self, coordinator: setattr(self, "coordinator", coordinator),
                "available": True}),
            "DataUpdateCoordinator": _FakeCoordinator,
            "UpdateFailed": type("UpdateFailed", (Exception,), {})},
    }
    saved = {n: sys.modules.get(n) for n in names}
    for n, attrs in names.items():
        m = types.ModuleType(n)
        m.__dict__.update(attrs)
        sys.modules[n] = m
    return saved


class _FakeCoordinator:
    def __init__(self, hass, logger, name, update_method, update_interval):
        self.update_method, self.data = update_method, None

    async def async_config_entry_first_refresh(self):
        self.data = await self.update_method()

    async def async_request_refresh(self):
        self.data = await self.update_method()


_saved = _install_ha_stubs()
try:
    from mitsubishi_outlander_phev_eu import binary_sensor as bs_mod  # noqa: E402
    from mitsubishi_outlander_phev_eu import button as button_mod  # noqa: E402
    from mitsubishi_outlander_phev_eu import client as factory  # noqa: E402
    from mitsubishi_outlander_phev_eu import const  # noqa: E402
    from mitsubishi_outlander_phev_eu import lock as lock_mod  # noqa: E402
    import importlib.util as _ilu  # noqa: E402
    _spec = _ilu.spec_from_file_location(
        "moe_real", _PKG / "__init__.py", submodule_search_locations=[str(_PKG)])
    integration = _ilu.module_from_spec(_spec)
    sys.modules["moe_real"] = integration
    _spec.loader.exec_module(integration)
    from mitsubishi_outlander_phev_eu.api import MitsubishiEUClient, VehicleState  # noqa: E402
finally:
    for _n, _m in _saved.items():
        if _m is None:
            sys.modules.pop(_n, None)
        else:
            sys.modules[_n] = _m


# ------------------------------------------------------------ 1: Tuerschloss
def _lock(doors_locked):
    ent = lock_mod.MitsubishiDoorLock.__new__(lock_mod.MitsubishiDoorLock)
    ent._optimistic_state = None
    ent.coordinator = SimpleNamespace(data=VehicleState(doors_locked=doors_locked))
    return ent


@pytest.mark.parametrize("raw,expected", [(None, None), (True, True), (False, False)])
def test_lock_is_locked_never_guesses(raw, expected):
    assert _lock(raw).is_locked is expected


def test_lock_without_state_is_unknown():
    ent = _lock(True)
    ent.coordinator = SimpleNamespace(data=None)
    assert ent.is_locked is None


@pytest.mark.parametrize("raw,expected", [(None, None), (True, False), (False, True)])
def test_binary_sensor_doors_locked_unknown_stays_none(raw, expected):
    desc = next(d for d in bs_mod.BINARY_SENSOR_DESCRIPTIONS if d.key == "doors_locked")
    assert desc.value_fn(VehicleState(doors_locked=raw)) is expected


# ------------------------------------------------- 2: Option "Auto aufwecken"
class _FakeClient:
    def __init__(self):
        self.refresh_calls = 0
        self.status_calls = 0
        self.state = VehicleState(battery_level=80, odometer=1000)

    async def async_login(self): return True
    async def async_get_vehicles(self): return [{"vin": "V1"}]
    async def async_close(self): pass

    async def async_refresh_status(self, vin):
        self.refresh_calls += 1
        return True

    async def async_get_vehicle_status(self, vin):
        self.status_calls += 1
        return self.state


def _setup(monkeypatch, options, client):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(integration.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(integration, "create_client", lambda data, **kw: client)

    async def forward(*a, **k): return True
    hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(async_forward_entry_setups=forward))
    entry = SimpleNamespace(
        entry_id="e", data={"username": "u", "password": "p", "pin": "1"}, options=options,
        add_update_listener=lambda cb: None, async_on_unload=lambda x: None)
    # DataUpdateCoordinator-Stub kennt hass nicht: Modul-Namen ersetzen
    monkeypatch.setattr(integration, "DataUpdateCoordinator", _FakeCoordinator)
    ok = asyncio.run(integration.async_setup_entry(hass, entry))
    assert ok
    return hass.data[const.DOMAIN]["e"], slept


def test_option_default_is_on_and_wakes_like_before(monkeypatch):
    assert const.DEFAULT_WAKE_ON_POLL is True
    client = _FakeClient()
    data, slept = _setup(monkeypatch, {}, client)
    assert client.refresh_calls == 1 and slept == [15]
    assert data["coordinators"]["V1"].wake_on_poll is True


def test_option_on_explicit_wakes(monkeypatch):
    client = _FakeClient()
    _setup(monkeypatch, {const.CONF_WAKE_ON_POLL: True}, client)
    assert client.refresh_calls == 1 and client.status_calls == 1


def test_option_off_never_calls_refresh_and_never_waits(monkeypatch):
    client = _FakeClient()
    data, slept = _setup(monkeypatch, {const.CONF_WAKE_ON_POLL: False}, client)
    assert client.refresh_calls == 0 and client.status_calls == 1
    assert slept == []
    assert data["coordinators"]["V1"].wake_on_poll is False


def test_option_off_empty_result_no_retry_loop_keeps_old_data(monkeypatch):
    client = _FakeClient()
    data, slept = _setup(monkeypatch, {const.CONF_WAKE_ON_POLL: False}, client)
    coord = data["coordinators"]["V1"]
    old = coord.data
    client.state = VehicleState()  # leer
    calls = client.status_calls
    assert asyncio.run(coord.update_method()) is old
    assert client.status_calls == calls + 1 and client.refresh_calls == 0 and slept == []


def test_option_off_empty_first_result_raises_update_failed(monkeypatch):
    client = _FakeClient()
    client.state = VehicleState()
    with pytest.raises(integration.UpdateFailed):
        _setup(monkeypatch, {const.CONF_WAKE_ON_POLL: False}, client)
    assert client.refresh_calls == 0 and client.status_calls == 1


def test_refresh_button_waits_when_wake_off(monkeypatch):
    slept = []

    async def fake_sleep(s): slept.append(s)
    monkeypatch.setattr(button_mod.asyncio, "sleep", fake_sleep)
    for wake, expected in ((False, [15]), (True, [])):
        slept.clear()
        ent = button_mod.MitsubishiRefreshButton.__new__(button_mod.MitsubishiRefreshButton)
        client = _FakeClient()
        refreshed = []

        async def req(): refreshed.append(1)
        ent._client, ent._vin = client, "V1"
        ent.coordinator = SimpleNamespace(wake_on_poll=wake, async_request_refresh=req)
        asyncio.run(ent.async_press())
        assert client.refresh_calls == 1 and slept == expected and refreshed == [1]


def test_options_flow_and_translations_have_the_option():
    src = (_PKG / "config_flow.py").read_text(encoding="utf-8")
    assert "CONF_WAKE_ON_POLL" in src
    for f in ("strings.json", "translations/en.json", "translations/de.json", "translations/ja.json"):
        d = json.loads((_PKG / f).read_text(encoding="utf-8"))["options"]["step"]["init"]
        assert d["data"]["wake_on_poll"] and d["data_description"]["wake_on_poll"], f


# ----------------------------------------------------------- 4: jp_2 -> jp_1
@pytest.mark.parametrize("old", ["jp_2", "jp_3", "jp"])
def test_old_jp_entries_run_as_jp1(old, caplog):
    caplog.set_level(logging.INFO)
    data = {"username": "u", "password": "p", "pin": "1", "region": old}
    assert factory.get_region(data) == ("jp" if old == "jp" else "jp_1")
    c = factory.create_client(data)
    assert isinstance(c, MitsubishiEUClient) and c._p is const.KINTARO_PROFILES["jp_1"]


def test_jp2_removed_from_dropdown_and_profiles():
    assert const.REGIONS == ["eu", "jp_1"]
    assert "jp_2" not in const.KINTARO_PROFILES


def test_eu_requests_unchanged_default_headers_and_client():
    c = factory.create_client({"username": "u", "password": "p", "pin": "1"})
    assert c._p is const.KINTARO_PROFILES["eu"]
    assert c._http.headers["user-agent"].startswith("python-httpx/")


# ------------------------------------------------------- 3: SSL / HTTP-Client
def test_ssl_context_is_passed_and_close_closes_own_client():
    import ssl
    ctx = ssl.create_default_context()
    c = MitsubishiEUClient("u", "p", "1", ssl_context=ctx)
    assert isinstance(c._http, httpx.AsyncClient) and not c._http.is_closed
    asyncio.run(c.async_close())
    assert c._http.is_closed


def test_create_client_without_ha_ssl_default_has_no_context():
    # Offline: ohne HA-Modul liefert _ssl_context() None -> alter Pfad
    assert factory._ssl_context() is None
    assert factory.create_client({"username": "u", "password": "p", "pin": "1"}, use_ha_ssl=True)


def test_no_blocking_asyncclient_without_context_in_setup_paths():
    for f in ("__init__.py", "config_flow.py"):
        src = (_PKG / f).read_text(encoding="utf-8")
        assert "create_client(" not in src or "use_ha_ssl=True" in src, f
