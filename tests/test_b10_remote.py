"""Offline tests v1.1.0b10: Fernbefehle wie die offizielle App 3.2.0 (Befund L366).

Je Befehl: hoechstens ein wakeUpVehicle (Sperre ueber wakeUpDuration, danach
WAKE_SETTLE_S warten) -> generateServerNonce mit frischer Client-Nonce -> Befehl
mit frischem pinHash (kein verifyPIN) -> getBatchRequestStatus bis duration.
Body von startClimate/startEngine wie MMCStartClimateRequest. Kein Nachversuch,
ausser Sitzungsverlust VOR der Annahme (dann Neu-Login + neuer Hash, einmal).

Keine Netzwerkzugriffe: _send ist ein nachgebauter Server, Verschluesselung und
Signatur sind durchgereicht, asyncio.sleep und die Wecksperren-Uhr sind ersetzt.
Testdaten sind erfunden (keine echte VIN/PIN).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
if "mitsubishi_outlander_phev_eu" not in sys.modules:
    _stub = types.ModuleType("mitsubishi_outlander_phev_eu")
    _stub.__path__ = [str(_PKG)]
    sys.modules["mitsubishi_outlander_phev_eu"] = _stub

from mitsubishi_outlander_phev_eu import api  # noqa: E402
from mitsubishi_outlander_phev_eu import const  # noqa: E402

VIN = "TESTVIN0000000001"
PIN = "4711"
PASSWORD = "geheimes-passwort-xyz"
HVAC = {"fanSpeed": "3", "frontDefroster": True, "rearDefroster": False,
        "seatHeater": {"driver": "2"}, "startDateTime": None}

WAKE = const.EP_WAKE_UP_VEHICLE
NONCE = const.EP_GENERATE_NONCE
VERIFY = const.EP_VERIFY_PIN
BATCH = const.EP_BATCH_REQUEST_STATUS


def run(coro):
    return asyncio.run(coro)


class Server:
    """Nachgebauter Kintaro-Server. Jeder Aufruf: (endpoint, body)."""

    def __init__(self, statuses=(2,), wake_duration=300, command=None, wake=None):
        self.calls: list[tuple[str, dict]] = []
        self.statuses = list(statuses)
        self.wake_duration = wake_duration
        self.command = command or {"state": "S", "requestId": "REQ-1",
                                   "pollingInterval": 5, "duration": 60}
        self.wake = wake
        self.nonce_counter = 0

    def names(self):
        return [c[0] for c in self.calls]

    def bodies(self, ep):
        return [b for n, b in self.calls if n == ep]

    def answer(self, name, body):
        if name == WAKE:
            if self.wake is not None:
                return self.wake
            return {"state": "S", "wakeUpDuration": self.wake_duration}
        if name == NONCE:
            self.nonce_counter += 1
            import base64
            return {"state": "S", "serverNonce": base64.b64encode(
                bytes([self.nonce_counter]) * 32).decode()}
        if name == VERIFY:
            return {"state": "S", "isValidPIN": True}
        if name == BATCH:
            st = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            rid = body["requestIdList"][0]["requestId"]
            return {"state": "S", "requestStatusList": [{"requestId": rid, "status": st}]}
        cmd = self.command
        return cmd(name, body) if callable(cmd) else cmd


class Harness:
    def __init__(self, monkeypatch, server: Server, pin=PIN):
        monkeypatch.setattr(api, "_encrypt_body", lambda body, key, p=None: body)
        monkeypatch.setattr(api, "_compute_sign", lambda *a, **k: "SIGN")
        self.sleeps: list[float] = []

        async def fake_sleep(s):
            self.sleeps.append(s)
        monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)
        self.now = 1000.0
        monkeypatch.setattr(api, "_monotonic", lambda: self.now)
        self.server = server
        self.client = api.MitsubishiEUClient("u@example.org", PASSWORD, pin)
        self.client._token = api.TokenState(
            access_token="AT", refresh_token="RT", expires_at=datetime.now() + timedelta(hours=1))
        self.client._enc_key = "K"
        self.client._sign_key = "S"
        self.client._internal_vins[VIN] = "IVIN1"
        # Alter gemerkter Hash darf fuer Befehle nie mehr verwendet werden
        self.client._pin_verified = True
        self.client._pin_hash = "ALTER-HASH"
        self.logins = 0
        self.client._send = self._send

        async def _refresh():
            self.logins += 1
            self.client._token = api.TokenState(
                access_token="AT2", refresh_token="RT",
                expires_at=datetime.now() + timedelta(hours=1))
            self.client._enc_key = "K"
            self.client._sign_key = "S"
            return True
        self.client.async_refresh_token = _refresh
        self.client.async_login = _refresh

    async def _send(self, method, name, url, **kw):
        body = json.loads(kw.get("content") or "{}")
        self.server.calls.append((name, body))
        a = self.server.answer(name, body)
        if isinstance(a, Exception):
            raise a
        return httpx.Response(200, json=a)


# ---------------------------------------------------------------- Reihenfolge
def test_order_wake_nonce_command_batch_and_settle(monkeypatch):
    srv = Server(statuses=(1, 2))
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is True
    assert srv.names() == [WAKE, NONCE, const.EP_START_CLIMATE, BATCH, BATCH]
    assert srv.bodies(WAKE) == [{"vin": VIN, "internalVin": "IVIN1"}]
    assert srv.bodies(BATCH)[0] == {"requestIdList": [{"requestId": "REQ-1"}]}
    assert h.sleeps == [const.WAKE_SETTLE_S, 5, 5]
    assert const.WAKE_SETTLE_S == 20  # b11: Obergrenze 10-20 s (vorher 15)
    assert h.client.last_error_code is None
    assert h.client.last_request_id == "REQ-1"


@pytest.mark.parametrize("method,endpoint", [
    ("async_stop_climate", const.EP_STOP_CLIMATE),
    ("async_lock_doors", const.EP_LOCK_DOOR),
    ("async_unlock_doors", const.EP_UNLOCK_DOOR),
    ("async_horn", const.EP_START_HORN),
    ("async_lights", const.EP_START_LIGHT),
    ("async_start_charging", const.EP_START_CHARGE),
    ("async_stop_engine", const.EP_STOP_ENGINE),
])
def test_all_remote_commands_use_same_flow(monkeypatch, method, endpoint):
    srv = Server()
    h = Harness(monkeypatch, srv)
    assert run(getattr(h.client, method)(VIN)) is True
    assert srv.names() == [WAKE, NONCE, endpoint, BATCH]
    body = srv.bodies(endpoint)[0]
    assert set(body) == {"vin", "internalVin", "pinHash"}
    assert body["pinHash"] != "ALTER-HASH"


# ---------------------------------------------------------------- frische Hashes
def test_two_commands_two_nonces_two_hashes_no_verify(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is True
    assert run(h.client.async_stop_climate(VIN)) is True
    assert VERIFY not in srv.names()
    nonces = [b["clientNonce"] for b in srv.bodies(NONCE)]
    assert len(nonces) == 2 and nonces[0] != nonces[1]
    import base64
    assert all(len(base64.b64decode(n)) == 32 for n in nonces)
    for b in srv.bodies(NONCE):
        assert b["vin"] == VIN and b["internalVin"] == "IVIN1"
    hashes = [srv.bodies(const.EP_START_CLIMATE)[0]["pinHash"],
              srv.bodies(const.EP_STOP_CLIMATE)[0]["pinHash"]]
    assert hashes[0] != hashes[1]
    assert "ALTER-HASH" not in hashes
    # Hash passt zur jeweiligen Nonce (gleicher Algorithmus wie bisher)
    server_nonce_1 = base64.b64encode(bytes([1]) * 32).decode()
    assert hashes[0] == api._compute_pin_hash(nonces[0], server_nonce_1, PIN)


def test_nonce_failure_sends_no_command(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv)
    orig = srv.answer
    srv.answer = lambda n, b: {"state": "F", "errorCode": "123"} if n == NONCE else orig(n, b)
    assert run(h.client.async_stop_climate(VIN)) is False
    assert const.EP_STOP_CLIMATE not in srv.names()
    assert h.client.last_error_code == "123"


def test_without_pin_no_command(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv, pin="")
    assert run(h.client.async_start_climate(VIN)) is False
    assert const.EP_START_CLIMATE not in srv.names()
    assert h.client.last_error_code == "no_pin"


# ---------------------------------------------------------------- Body
@pytest.mark.parametrize("method,endpoint", [
    ("async_start_climate", const.EP_START_CLIMATE),
    ("async_start_engine", const.EP_START_ENGINE),
])
def test_body_like_app_with_last_climate(monkeypatch, method, endpoint):
    srv = Server()
    h = Harness(monkeypatch, srv)
    h.client._last_climate[VIN] = {"isACOn": False, "targetTemperature": 21.5, "hvacSettings": HVAC}
    assert run(getattr(h.client, method)(VIN)) is True
    body = srv.bodies(endpoint)[0]
    assert set(body) == {"vin", "internalVin", "pinHash", "targetTemperature",
                         "temperatureUnit", "hvacSettings"}
    assert body["targetTemperature"] == "21.5"
    assert isinstance(body["targetTemperature"], str)
    assert body["temperatureUnit"] == "C"
    assert body["hvacSettings"] == HVAC
    assert "action" not in body and "startFlag" not in body


def test_body_passed_temperature_wins_one_decimal(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv)
    h.client._last_climate[VIN] = {"targetTemperature": 19.0, "hvacSettings": HVAC}
    run(h.client.async_start_climate(VIN, temperature=22))
    assert srv.bodies(const.EP_START_CLIMATE)[0]["targetTemperature"] == "22.0"


@pytest.mark.parametrize("method,endpoint", [
    ("async_start_climate", const.EP_START_CLIMATE),
    ("async_start_engine", const.EP_START_ENGINE),
])
def test_body_defaults_without_climate_data(monkeypatch, method, endpoint):
    srv = Server()
    h = Harness(monkeypatch, srv)
    run(getattr(h.client, method)(VIN))
    body = srv.bodies(endpoint)[0]
    assert body["targetTemperature"] == "25.0"
    assert body["temperatureUnit"] == "C"
    assert "hvacSettings" not in body
    assert "action" not in body and "startFlag" not in body


def test_status_read_remembers_climate_details(monkeypatch):
    """getClimateDetails aus der Statusabfrage landet unveraendert im naechsten Befehl."""
    srv = Server()
    h = Harness(monkeypatch, srv)
    climate = {"isACOn": True, "targetTemperature": "23", "hvacSettings": HVAC}

    async def fake_get_ex(endpoint, params=None):
        if endpoint == const.EP_CLIMATE_DETAILS:
            return climate, False
        return None, False
    h.client._kintaro_get_ex = fake_get_ex
    h.client._vehicles_cache = [{"vin": VIN}]
    state = run(h.client._read_vehicle_status(VIN))
    assert state.raw_data["climate"]["hvacSettings"] == HVAC
    srv.calls.clear()
    run(h.client.async_start_climate(VIN))
    body = srv.bodies(const.EP_START_CLIMATE)[0]
    assert body["hvacSettings"] == HVAC and body["targetTemperature"] == "23.0"


# ---------------------------------------------------------------- Wecksperre
def test_wake_lock_uses_wakeupduration(monkeypatch):
    srv = Server(wake_duration=120)
    h = Harness(monkeypatch, srv)
    run(h.client.async_stop_climate(VIN))
    h.now += 60
    h.sleeps.clear()
    run(h.client.async_stop_climate(VIN))
    assert srv.names().count(WAKE) == 1
    assert const.WAKE_SETTLE_S not in h.sleeps  # kein Weckruf -> keine Wartezeit
    h.now += 61
    run(h.client.async_stop_climate(VIN))
    assert srv.names().count(WAKE) == 2


def test_wake_failure_only_warns_and_sends_command(monkeypatch, caplog):
    srv = Server(wake={"state": "F", "errorCode": "777"})
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.WARNING):
        assert run(h.client.async_start_climate(VIN)) is True
    assert srv.names() == [WAKE, NONCE, const.EP_START_CLIMATE, BATCH]
    assert const.WAKE_SETTLE_S not in h.sleeps
    assert "wakeUpVehicle" in caplog.text
    # nach gescheitertem Wecken keine Sperre: naechster Befehl weckt erneut
    run(h.client.async_stop_climate(VIN))
    assert srv.names().count(WAKE) == 2


def test_wake_network_error_still_sends(monkeypatch):
    srv = Server(wake=httpx.ConnectError("boom"))
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_stop_climate(VIN)) is True
    assert srv.names().count(WAKE) == 1
    assert const.EP_STOP_CLIMATE in srv.names()


# ---------------------------------------------------------------- Polling
def test_status_3_is_rejected(monkeypatch, caplog):
    srv = Server(statuses=(1, 3))
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.WARNING):
        assert run(h.client.async_start_climate(VIN)) is False
    assert h.client.last_error_code == "vehicle_rejected:3"
    assert srv.names().count(BATCH) == 2
    assert "REQ-1" in caplog.text and "Status 3" in caplog.text
    assert srv.names().count(const.EP_START_CLIMATE) == 1


def test_only_running_until_duration_is_no_response(monkeypatch, caplog):
    srv = Server(statuses=(1,), command={"state": "S", "requestId": "REQ-9",
                                         "pollingInterval": 5, "duration": 30})
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.WARNING):
        assert run(h.client.async_start_climate(VIN)) is False
    assert h.client.last_error_code == "vehicle_no_response"
    assert srv.names().count(BATCH) == 6
    assert h.sleeps == [const.WAKE_SETTLE_S] + [5] * 6
    assert srv.names().count(const.EP_START_CLIMATE) == 1
    assert "REQ-9" in caplog.text


def test_polling_defaults_and_cap(monkeypatch):
    srv = Server(statuses=(1,), command={"state": "S", "requestId": "R"})
    h = Harness(monkeypatch, srv)
    run(h.client.async_stop_climate(VIN))
    assert srv.names().count(BATCH) == 12  # 60 s / 5 s
    srv2 = Server(statuses=(1,), command={"state": "S", "requestId": "R",
                                          "pollingInterval": 10, "duration": 999})
    h2 = Harness(monkeypatch, srv2)
    run(h2.client.async_stop_climate(VIN))
    assert srv2.names().count(BATCH) == 18  # Deckel 180 s / 10 s


def test_batch_errors_keep_polling_without_resend(monkeypatch):
    srv = Server(statuses=(2,))
    h = Harness(monkeypatch, srv)
    orig = srv.answer
    seen = {"n": 0}

    def ans(n, b):
        if n == BATCH:
            seen["n"] += 1
            if seen["n"] == 1:
                return httpx.ReadTimeout("t")
        return orig(n, b)
    srv.answer = ans
    assert run(h.client.async_stop_climate(VIN)) is True
    assert srv.names().count(const.EP_STOP_CLIMATE) == 1
    assert srv.names().count(BATCH) == 2


def test_without_request_id_state_s_counts_as_accepted(monkeypatch, caplog):
    srv = Server(command={"state": "S"})
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.INFO):
        assert run(h.client.async_start_climate(VIN)) is True
    assert BATCH not in srv.names()
    assert "keine requestId" in caplog.text


def test_polling_never_faster_than_5s_and_no_extra_status_calls(monkeypatch):
    """Nachtrag Thomas: Mitsubishi drosselt. Nur getBatchRequestStatus im Server-Takt,
    mindestens 5 s, kein refreshVSR/getClimateDetails/VSR rund um den Befehl."""
    srv = Server(statuses=(1, 1, 2), command={"state": "S", "requestId": "R",
                                              "pollingInterval": 1, "duration": 60})
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is True
    assert h.sleeps == [const.WAKE_SETTLE_S, 5, 5, 5]
    allowed = {WAKE, NONCE, const.EP_START_CLIMATE, BATCH}
    assert set(srv.names()) <= allowed
    assert srv.names().count(BATCH) == 3  # Abbruch direkt nach Status 2


@pytest.mark.parametrize("statuses,command,result,status,error", [
    ((2,), None, "ok", 2, None),
    ((3,), None, "rejected", 3, "vehicle_rejected:3"),
    ((1,), None, "no_response", 1, "vehicle_no_response"),
    ((2,), {"state": "S"}, "accepted_no_request_id", None, None),
    ((2,), {"state": "F", "errorCode": "950400"}, "failed", None, "950400"),
])
def test_last_climate_command_attribute_data(monkeypatch, caplog, statuses, command, result, status, error):
    srv = Server(statuses=statuses, command=command)
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.INFO):
        run(h.client.async_start_climate(VIN))
    last = h.client.last_climate_command[VIN]
    assert {"command", "result", "request_id", "status", "error", "at"} <= set(last)  # b11: + Diagnose
    assert last["command"] == "startClimate"
    assert last["result"] == result and last["status"] == status and last["error"] == error
    assert VIN not in json.dumps(last) and PIN not in json.dumps(last)
    assert f"Fernbefehl startClimate [Region=eu]: Ergebnis {result}" in caplog.text


def test_non_climate_commands_do_not_touch_climate_attribute(monkeypatch):
    srv = Server()
    h = Harness(monkeypatch, srv)
    run(h.client.async_horn(VIN))
    assert VIN not in h.client.last_climate_command
    run(h.client.async_start_engine(VIN))
    assert h.client.last_climate_command[VIN]["command"] == "startEngine"


# ---------------------------------------------------------------- kein zweites Senden
@pytest.mark.parametrize("statuses", [(3,), (1,)])
def test_failed_command_is_never_sent_twice(monkeypatch, statuses):
    srv = Server(statuses=statuses)
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is False
    assert srv.names().count(const.EP_START_CLIMATE) == 1
    assert srv.names().count(WAKE) == 1
    assert srv.names().count(NONCE) == 1


def test_command_network_error_not_resent(monkeypatch):
    srv = Server(command=httpx.ReadTimeout("t"))
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is False
    assert srv.names().count(const.EP_START_CLIMATE) == 1
    assert BATCH not in srv.names()


def test_server_rejection_not_resent(monkeypatch):
    srv = Server(command={"state": "F", "errorCode": "950400"})
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_charging(VIN)) is False
    assert srv.names().count(const.EP_START_CHARGE) == 1
    assert h.client.last_error_code == "950400"


def test_session_loss_before_acceptance_relogin_new_hash_once(monkeypatch):
    """Sitzungsverlust (600002): Server hat den Befehl NICHT angenommen -> Neu-Login,
    neue Nonce, neuer Hash, genau einmal neu senden. Kein zweiter Weckruf."""
    answers = iter([{"state": "F", "errorCode": "600002"},
                    {"state": "S", "requestId": "R2", "pollingInterval": 5, "duration": 60}])
    srv = Server(command=lambda n, b: next(answers))
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_start_climate(VIN)) is True
    assert srv.names() == [WAKE, NONCE, const.EP_START_CLIMATE, NONCE,
                           const.EP_START_CLIMATE, BATCH]
    assert h.logins == 1
    hashes = [b["pinHash"] for b in srv.bodies(const.EP_START_CLIMATE)]
    assert hashes[0] != hashes[1]


def test_session_loss_twice_gives_up(monkeypatch):
    srv = Server(command={"state": "F", "errorCode": "600002"})
    h = Harness(monkeypatch, srv)
    assert run(h.client.async_stop_climate(VIN)) is False
    assert srv.names().count(const.EP_STOP_CLIMATE) == 2
    assert h.client.last_error_code == api.FORCE_LOGOUT_CODE


def test_accepted_command_never_resent_even_if_session_dies_while_polling(monkeypatch):
    srv = Server(statuses=(2,))
    h = Harness(monkeypatch, srv)
    orig = srv.answer
    srv.answer = lambda n, b: {"state": "F", "errorCode": "600002"} if n == BATCH else orig(n, b)
    run(h.client.async_start_climate(VIN))
    assert srv.names().count(const.EP_START_CLIMATE) == 1


# ---------------------------------------------------------------- keine Secrets im Log
def test_log_has_no_vin_pin_password(monkeypatch, caplog):
    srv = Server(statuses=(1,))
    h = Harness(monkeypatch, srv)
    with caplog.at_level(logging.DEBUG):
        run(h.client.async_start_climate(VIN))
        h.now += 1000
        srv.wake = {"state": "F", "errorCode": "1"}
        run(h.client.async_stop_climate(VIN))
    for secret in (VIN, PIN, PASSWORD, "IVIN1"):
        assert secret not in caplog.text


def test_location_still_uses_remembered_hash():
    src = (_PKG / "api.py").read_text(encoding="utf-8")
    loc = src[src.index("EP_VEHICLE_LOCATION, {"):][:200]
    assert "self._pin_hash" in loc
    cmd = src[src.index("async def _send_vehicle_command"):src.index("async def async_stop_climate")]
    assert "self._pin_hash" not in cmd and "_ensure_pin" not in cmd


def test_manifest_version_b10():
    m = json.loads((_PKG / "manifest.json").read_text(encoding="utf-8"))
    assert m["version"].startswith("1.1.0b1")  # b11 baut auf b10 auf


# ---------------------------------------------------------------- Entitaeten
def _load_entities():
    from test_b4 import _install_ha_stubs
    saved = _install_ha_stubs()
    extra = {
        "homeassistant.components.switch": {"SwitchEntity": type("SwitchEntity", (), {})},
        "homeassistant.components.climate": {
            "ClimateEntity": type("ClimateEntity", (), {}),
            "ClimateEntityFeature": SimpleNamespace(TARGET_TEMPERATURE=1),
            "HVACMode": SimpleNamespace(OFF="off", HEAT_COOL="heat_cool")},
        "homeassistant.helpers.entity_registry": {},
    }
    for n, attrs in extra.items():
        saved.setdefault(n, sys.modules.get(n))
        m = types.ModuleType(n)
        m.__dict__.update(attrs)
        sys.modules[n] = m
    sys.modules["homeassistant.const"].UnitOfTemperature = SimpleNamespace(CELSIUS="°C")
    try:
        from mitsubishi_outlander_phev_eu import climate as climate_mod
        from mitsubishi_outlander_phev_eu import coordinator as coord_mod
        from mitsubishi_outlander_phev_eu import switch as switch_mod
        coord_mod.HomeAssistantError = _HAError  # Stub-Fehler mit translation_*-Argumenten
    finally:
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
    return switch_mod, climate_mod, coord_mod


class _HAError(Exception):
    def __init__(self, *a, **kw):
        super().__init__(*a)
        self.kw = kw


class _FakeClient:
    def __init__(self, ok, code=None):
        self.ok, self.code = ok, code
        self.last_error_code = None
        self.last_request_id = "REQ-7"
        self.calls = []

    async def _do(self, name, *a, **k):
        self.calls.append(name)
        self.last_error_code = self.code
        return self.ok

    async def async_start_climate(self, vin, temperature=None):
        return await self._do("start", temperature)

    async def async_stop_climate(self, vin):
        return await self._do("stop")


def _entity(cls, client, ac_on):
    ent = cls.__new__(cls)
    ent._client, ent._vin = client, VIN
    ent._optimistic_state = None
    ent._optimistic_mode = None
    ent._optimistic_temp = None
    ent.written = []
    refreshed = []

    async def req():
        refreshed.append(1)
    ent.coordinator = SimpleNamespace(
        data=api.VehicleState(vin=VIN, ac_on=ac_on, target_temperature=21.0),
        async_request_refresh=req)
    ent.refreshed = refreshed
    return ent


def _record(ent, attr):
    ent.async_write_ha_state = lambda: ent.written.append(getattr(ent, attr))


@pytest.fixture
def no_sleep(monkeypatch):
    async def fake_sleep(s):
        return None
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


def test_switch_optimistic_then_success(no_sleep):
    switch_mod, _, _ = _load_entities()
    ent = _entity(switch_mod.MitsubishiClimateSwitch, _FakeClient(True), ac_on=False)
    _record(ent, "is_on")
    run(ent.async_turn_on())
    assert ent.written[0] is True  # sofort optimistisch an
    assert ent.refreshed == [1]


def test_switch_exposes_last_command_attribute():
    switch_mod, _, _ = _load_entities()
    client = _FakeClient(True)
    ent = _entity(switch_mod.MitsubishiClimateSwitch, client, ac_on=False)
    assert ent.extra_state_attributes is None
    client.last_climate_command = {VIN: {"command": "startClimate", "result": "ok",
                                         "request_id": "R", "status": 2, "error": None, "at": "x"}}
    assert ent.extra_state_attributes["last_command"]["result"] == "ok"


@pytest.mark.parametrize("code,key", [
    ("vehicle_no_response", "vehicle_no_response"),
    ("vehicle_rejected:3", "vehicle_rejected"),
    ("950400", "command_rejected"),
])
def test_switch_reverts_and_raises_understandable_error(no_sleep, code, key, caplog):
    switch_mod, _, coord_mod = _load_entities()
    client = _FakeClient(False, code)
    ent = _entity(switch_mod.MitsubishiClimateSwitch, client, ac_on=False)
    _record(ent, "is_on")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(coord_mod.HomeAssistantError):
            run(ent.async_turn_on())
    assert ent.written == [True, False]  # optimistisch an, dann zurueck auf alt (aus)
    assert ent._optimistic_state is None
    assert client.calls == ["start"]
    assert ent.refreshed == []
    assert "REQ-7" in caplog.text and VIN not in caplog.text


def test_raise_command_rejected_keys(monkeypatch):
    _, _, coord_mod = _load_entities()
    got = {}

    class Err(Exception):
        def __init__(self, **kw):
            got.update(kw)
    monkeypatch.setattr(coord_mod, "HomeAssistantError", Err)
    with pytest.raises(Err):
        coord_mod.raise_command_rejected(SimpleNamespace(last_error_code="vehicle_rejected:4"), VIN, "startClimate")
    assert got["translation_key"] == "vehicle_rejected"
    assert got["translation_placeholders"] == {"command": "startClimate", "status": "4"}
    with pytest.raises(Err):
        coord_mod.raise_command_rejected(SimpleNamespace(last_error_code="vehicle_no_response"), VIN, "stopClimate")
    assert got["translation_key"] == "vehicle_no_response"
    assert got["translation_placeholders"] == {"command": "stopClimate"}


def test_translations_have_new_exception_keys():
    for name in ("strings.json", "translations/en.json", "translations/de.json", "translations/ja.json"):
        exc = json.loads((_PKG / name).read_text(encoding="utf-8"))["exceptions"]
        assert "{command}" in exc["vehicle_no_response"]["message"]
        assert "{status}" in exc["vehicle_rejected"]["message"]


def test_climate_entity_reverts_on_failure(no_sleep):
    _, climate_mod, coord_mod = _load_entities()
    client = _FakeClient(False, "vehicle_no_response")
    ent = _entity(climate_mod.MitsubishiClimateEntity, client, ac_on=False)
    _record(ent, "hvac_mode")
    with pytest.raises(coord_mod.HomeAssistantError):
        run(ent.async_set_hvac_mode("heat_cool"))
    assert ent.written == ["heat_cool", "off"]
    assert client.calls == ["start"]


def test_climate_entity_success_refreshes(no_sleep):
    _, climate_mod, _ = _load_entities()
    client = _FakeClient(True)
    ent = _entity(climate_mod.MitsubishiClimateEntity, client, ac_on=True)
    _record(ent, "hvac_mode")
    run(ent.async_set_hvac_mode("off"))
    assert ent.written[0] == "off" and ent.refreshed == [1]
