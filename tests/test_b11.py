"""Offline tests v1.1.0b11: Motor-Remote-Schalter (Diagnose), Dienst request_status,
Diagnosefelder in last_command, WAKE_SETTLE_S = 20.

Keine Netzwerkzugriffe (nachgebauter Server aus test_b10_remote). Testdaten erfunden.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from test_b10_remote import (  # noqa: E402
    BATCH, HVAC, NONCE, PIN, PASSWORD, VIN, WAKE, Harness, Server, _FakeClient, _PKG,
    _entity, _load_entities, _record, api, const, run,
)


def _without_hash(body):
    return {k: v for k, v in body.items() if k != "pinHash"}


# ---------------------------------------------------------------- startEngine/stopEngine
def test_start_engine_endpoint_and_flow(monkeypatch):
    srv = Server(statuses=(1, 2))
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_engine(VIN)) is True
    assert srv.names() == [WAKE, NONCE, const.EP_START_ENGINE, BATCH, BATCH]
    assert const.EP_START_ENGINE == "/remote/startEngine/v1"
    assert h.sleeps == [20, 5, 5]


def test_start_engine_body_identical_to_start_climate(monkeypatch):
    bodies = {}
    for method, ep in (("async_start_climate", const.EP_START_CLIMATE),
                       ("async_start_engine", const.EP_START_ENGINE)):
        srv = Server(statuses=(2,))
        h = Harness(monkeypatch, srv)
        h.client._last_climate[VIN] = {"targetTemperature": 22, "hvacSettings": HVAC}
        assert run(getattr(h.client, method)(VIN)) is True
        (body,) = srv.bodies(ep)
        assert body["pinHash"] and body["pinHash"] != "ALTER-HASH"
        bodies[ep] = _without_hash(body)
    assert bodies[const.EP_START_ENGINE] == bodies[const.EP_START_CLIMATE]
    assert bodies[const.EP_START_ENGINE] == {
        "vin": VIN, "internalVin": "IVIN1", "targetTemperature": "22.0",
        "temperatureUnit": "C", "hvacSettings": HVAC}
    # nicht der nackte _remote_command-Body
    assert set(bodies[const.EP_START_ENGINE]) != {"vin", "internalVin"}


def test_stop_engine_fresh_hash(monkeypatch):
    srv = Server(statuses=(2,))
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_stop_engine(VIN)) is True
    assert srv.names() == [WAKE, NONCE, const.EP_STOP_ENGINE, BATCH]
    (body,) = srv.bodies(const.EP_STOP_ENGINE)
    assert _without_hash(body) == {"vin": VIN, "internalVin": "IVIN1"}
    assert body["pinHash"] != "ALTER-HASH"


@pytest.mark.parametrize("statuses", [(1,), (3,)])
def test_start_engine_no_retry(monkeypatch, statuses):
    srv = Server(statuses=statuses)
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_engine(VIN)) is False
    assert srv.names().count(const.EP_START_ENGINE) == 1
    assert srv.names().count(WAKE) == 1 and srv.names().count(NONCE) == 1


def test_engine_command_has_own_attribute(monkeypatch):
    srv = Server(statuses=(2,))
    h = Harness(monkeypatch, srv)
    run(h.client.async_start_climate(VIN))
    assert VIN not in h.client.last_engine_command
    run(h.client.async_start_engine(VIN))
    assert h.client.last_engine_command[VIN]["command"] == "startEngine"
    assert h.client.last_climate_command[VIN]["command"] == "startEngine"


# ---------------------------------------------------------------- Diagnosefelder
DIAG = {"wake", "wake_up_duration", "duration", "polling_interval", "polls", "elapsed_s"}


def test_diag_fields_ok_and_info_line(monkeypatch, caplog):
    srv = Server(statuses=(1, 2), command={"state": "S", "requestId": "REQ-1",
                                           "pollingInterval": 5, "duration": 80})
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.INFO):
        assert run(h.client.async_start_climate(VIN)) is True
    last = h.client.last_climate_command[VIN]
    assert DIAG <= set(last)
    assert last["wake"] == "ran" and last["wake_up_duration"] == 300
    assert last["duration"] == 80 and last["polling_interval"] == 5
    assert last["polls"] == 2 and isinstance(last["elapsed_s"], float)
    recs = [r for r in caplog.records if r.getMessage().startswith("Fernbefehl startClimate")]
    assert len(recs) == 1 and recs[0].levelno == logging.INFO
    msg = recs[0].getMessage()
    for part in ("wake=ran", "wakeUpDuration=300", "duration=80", "pollingInterval=5",
                 "Statusabfragen=2", "Gesamtdauer="):
        assert part in msg


def test_diag_no_response_is_warning_and_counts_polls(monkeypatch, caplog):
    srv = Server(statuses=(1,), command={"state": "S", "requestId": "REQ-1",
                                         "pollingInterval": 5, "duration": 80})
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.INFO):
        assert run(h.client.async_start_engine(VIN)) is False
    last = h.client.last_engine_command[VIN]
    assert last["result"] == "no_response" and last["polls"] == 16
    recs = [r for r in caplog.records if r.getMessage().startswith("Fernbefehl startEngine")]
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING


def test_diag_wake_skipped_lock_then_failed(monkeypatch):
    srv = Server(statuses=(2,))
    h = Harness(monkeypatch, srv)
    run(h.client.async_start_climate(VIN))
    run(h.client.async_stop_climate(VIN))
    assert h.client.last_climate_command[VIN]["wake"] == "skipped_lock"
    assert h.client.last_climate_command[VIN]["wake_up_duration"] is None
    srv2 = Server(statuses=(2,), wake={"state": "F", "errorCode": "123"})
    h2 = Harness(monkeypatch, srv2)
    run(h2.client.async_start_climate(VIN))
    assert h2.client.last_climate_command[VIN]["wake"] == "failed"


def test_diag_failed_command_has_fields(monkeypatch):
    srv = Server(command={"state": "F", "errorCode": "950400"})
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is False
    last = h.client.last_climate_command[VIN]
    assert last["result"] == "failed" and last["polls"] == 0 and last["duration"] is None


def test_diag_no_secrets(monkeypatch, caplog):
    srv = Server(statuses=(1, 3))
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.DEBUG):
        run(h.client.async_start_engine(VIN))
        run(h.client.async_request_status("REQ-1"))
    dumped = json.dumps(h.client.last_engine_command[VIN])
    for secret in (VIN, PIN, PASSWORD, "AT", "IVIN1"):
        assert secret not in dumped
    for secret in (VIN, PASSWORD, "IVIN1"):
        assert secret not in caplog.text


def test_wake_settle_is_20():
    assert const.WAKE_SETTLE_S == 20


# ---------------------------------------------------------------- request_status (Client)
def test_request_status_exactly_one_call_no_wake_no_command(monkeypatch, caplog):
    def cmd(name, body):
        raise AssertionError(f"unerwarteter Aufruf {name}")
    srv = Server(statuses=(2,), command=cmd)
    h = Harness(monkeypatch, srv)
    orig = srv.answer

    def answer(name, body):
        a = orig(name, body)
        if name == BATCH:
            a["requestStatusList"][0].update({"vin": VIN, "internalVin": "IVIN1"})
        return a
    srv.answer = answer
    with caplog.at_level(logging.INFO):
        res = run(h.client.async_request_status("REQ-9"))
    assert srv.names() == [BATCH]
    assert srv.bodies(BATCH) == [{"requestIdList": [{"requestId": "REQ-9"}]}]
    assert res["status"] == 2 and res["error"] is None and res["request_id"] == "REQ-9"
    assert res["request_status_list"] == [{"requestId": "REQ-9", "status": 2}]
    assert VIN not in json.dumps(res) and "IVIN1" not in json.dumps(res)
    assert h.logins == 0 and h.sleeps == []
    assert "Dienst request_status" in caplog.text and "REQ-9" in caplog.text


def test_request_status_without_session_no_call_no_login(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv)
    h.client._token = api.TokenState(access_token="AT", refresh_token="RT",
                                     expires_at=datetime.now() - timedelta(hours=1))
    res = run(h.client.async_request_status("REQ-9"))
    assert srv.calls == [] and h.logins == 0
    assert res["error"] == "no_session" and res["status"] is None


def test_request_status_rejected_no_retry(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv)
    srv.answer = lambda name, body: {"state": "F", "errorCode": "900000"}
    res = run(h.client.async_request_status("REQ-9"))
    assert srv.names() == [BATCH] and h.logins == 0
    assert res["error"] == "900000" and res["request_status_list"] == []


# ---------------------------------------------------------------- Dienst (services.py)
def _load_services():
    from test_b4 import _install_ha_stubs
    saved = _install_ha_stubs()
    try:
        sys.modules.pop("mitsubishi_outlander_phev_eu.services", None)
        from mitsubishi_outlander_phev_eu import services as svc
    finally:
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m

    class _SVE(Exception):
        def __init__(self, *a, **kw):
            super().__init__(*a)
            self.kw = kw
    svc.ServiceValidationError = _SVE
    return svc


class _SvcClient:
    def __init__(self):
        self.calls = []

    async def async_request_status(self, rid):
        self.calls.append(rid)
        return {"request_id": rid, "status": 1, "request_status_list": [], "error": None}

    def __getattr__(self, name):  # jeder andere Aufruf (Befehl, Login, Wecken) ist verboten
        raise AssertionError(f"unerwarteter Zugriff {name}")


def _hass(entries):
    return SimpleNamespace(data={const.DOMAIN: entries, f"{const.DOMAIN}_sessions": {}})


def test_service_handler_one_call_only():
    svc = _load_services()
    c = _SvcClient()
    hass = _hass({"e1": {"client": c, "coordinators": {VIN: object()}}})
    res = run(svc._async_request_status(SimpleNamespace(hass=hass, data={"request_id": "R1"})))
    assert c.calls == ["R1"] and res["status"] == 1


def test_service_handler_picks_entry_by_vin_or_id():
    svc = _load_services()
    a, b = _SvcClient(), _SvcClient()
    hass = _hass({"e1": {"client": a, "coordinators": {"OTHERVIN": 1}},
                  "e2": {"client": b, "coordinators": {VIN: 1}}})
    run(svc._async_request_status(SimpleNamespace(hass=hass, data={"request_id": "R", "vin": VIN})))
    run(svc._async_request_status(SimpleNamespace(hass=hass, data={"request_id": "S", "config_entry_id": "e1"})))
    assert a.calls == ["S"] and b.calls == ["R"]
    with pytest.raises(svc.ServiceValidationError):
        run(svc._async_request_status(SimpleNamespace(hass=hass, data={"request_id": "T"})))
    with pytest.raises(svc.ServiceValidationError):
        run(svc._async_request_status(SimpleNamespace(hass=_hass({}), data={"request_id": "T"})))


def test_service_registered_with_response_only():
    svc = _load_services()
    reg = []
    services = SimpleNamespace(has_service=lambda d, s: bool(reg),
                               async_register=lambda *a, **k: reg.append((a, k)))
    hass = SimpleNamespace(services=services)
    svc.async_setup_services(hass)
    svc.async_setup_services(hass)
    assert len(reg) == 1
    (args, kw), = reg
    assert args[:2] == (const.DOMAIN, "request_status")
    assert kw["supports_response"] == "only"
    assert kw["schema"]({"request_id": "R"}) == {"request_id": "R"}


def test_services_yaml_and_translations():
    y = (_PKG / "services.yaml").read_text(encoding="utf-8")
    assert y.startswith("request_status:") and "required: true" in y
    for name in ("strings.json", "translations/en.json", "translations/de.json", "translations/ja.json"):
        d = json.loads((_PKG / name).read_text(encoding="utf-8"))
        assert set(d["services"]["request_status"]["fields"]) == {"request_id", "config_entry_id", "vin"}
        assert d["entity"]["switch"]["remote_engine"]["name"]
        assert {"entry_not_found", "entry_ambiguous"} <= set(d["exceptions"])
    de = json.loads((_PKG / "translations/de.json").read_text(encoding="utf-8"))
    assert de["entity"]["switch"]["remote_engine"]["name"] == "Motor-Remote (Diagnose)"


# ---------------------------------------------------------------- Schalter
class _EngineClient(_FakeClient):
    async def async_start_engine(self, vin, temperature=None):
        return await self._do("start_engine")

    async def async_stop_engine(self, vin):
        return await self._do("stop_engine")


@pytest.fixture
def no_sleep(monkeypatch):
    async def fake_sleep(s):
        return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


def test_engine_switch_basics():
    switch_mod, _, _ = _load_entities()
    cls = switch_mod.MitsubishiRemoteEngineSwitch
    ent = cls.__new__(cls)
    switch_mod.MitsubishiClimateSwitch.__init__ = lambda self, c, v, i, cl: None
    try:
        cls.__init__(ent, None, VIN, {}, None)
    finally:
        del switch_mod.MitsubishiClimateSwitch.__init__
    assert ent._attr_translation_key == "remote_engine"
    assert ent._attr_icon == "mdi:engine"
    assert ent._attr_entity_registry_enabled_default is False


def test_engine_switch_unique_id_in_source():
    src = (_PKG / "switch.py").read_text(encoding="utf-8")
    assert 'f"{vin}_remote_engine"' in src
    assert "MitsubishiRemoteEngineSwitch(coordinator, vin, vehicle_info, client)" in src


def test_engine_switch_on_off_and_state(no_sleep):
    switch_mod, _, _ = _load_entities()
    client = _EngineClient(True)
    ent = _entity(switch_mod.MitsubishiRemoteEngineSwitch, client, ac_on=True)
    assert ent.is_on is False  # engine_on, nicht ac_on
    _record(ent, "is_on")
    run(ent.async_turn_on())
    run(ent.async_turn_off())
    assert client.calls == ["start_engine", "stop_engine"]
    assert ent.written[0] is True and ent.refreshed == [1, 1]
    attrs = ent.extra_state_attributes
    assert "Benzinmotor" in attrs["warning"] and "last_command" not in attrs
    client.last_engine_command = {VIN: {"command": "startEngine", "result": "ok"}}
    assert ent.extra_state_attributes["last_command"]["command"] == "startEngine"


def test_engine_switch_failure_same_error(no_sleep):
    switch_mod, _, coord_mod = _load_entities()
    client = _EngineClient(False, "vehicle_no_response")
    ent = _entity(switch_mod.MitsubishiRemoteEngineSwitch, client, ac_on=False)
    _record(ent, "is_on")
    with pytest.raises(coord_mod.HomeAssistantError) as ei:
        run(ent.async_turn_on())
    assert ei.value.kw["translation_key"] == "vehicle_no_response"
    assert ei.value.kw["translation_placeholders"] == {"command": "startEngine"}
    assert ent.written == [True, False] and client.calls == ["start_engine"]


def test_manifest_version_b11():
    m = json.loads((_PKG / "manifest.json").read_text(encoding="utf-8"))
    assert m["version"] == "1.1.0"
