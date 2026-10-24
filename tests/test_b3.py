"""Offline tests v1.1.0b3: Login-Encoding, Timeouts, optionale Endpoints, Debug-Log, V3 entfernt.

Keine Netzwerkzugriffe: httpx laeuft ueber MockTransport.
"""
import asyncio
import json
import logging
import re
import sys
import types
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
if "mitsubishi_outlander_phev_eu" not in sys.modules:
    _stub = types.ModuleType("mitsubishi_outlander_phev_eu")
    _stub.__path__ = [str(_PKG)]
    sys.modules["mitsubishi_outlander_phev_eu"] = _stub

from mitsubishi_outlander_phev_eu import api as api_mod  # noqa: E402
from mitsubishi_outlander_phev_eu import client as factory  # noqa: E402
from mitsubishi_outlander_phev_eu import const  # noqa: E402
from mitsubishi_outlander_phev_eu.api import MitsubishiEUClient, TokenState  # noqa: E402

NASTY = [
    "plain",
    "pa%ss#word",
    "a&b=c+d?e/f",
    "% # & + = ? /",
    "mit Leerzeichen  und\ttab",
    "Pässwörd-ä",
    "100%25 #1 &x=1",
    "+++",
]


def _login_request(region, user, pw):
    """Echten Login-Request (Bytes) ueber MockTransport mitschneiden."""
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = request.content
        seen["ctype"] = request.headers["content-type"]
        seen["url"] = str(request.url)
        return httpx.Response(401, json={"error": "x"})

    async def run():
        c = MitsubishiEUClient(user, pw, "1234", region=region)
        await c._http.aclose()
        c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=api_mod.HTTP_TIMEOUT)
        await c.async_login()
        await c.async_close()
        return c

    c = asyncio.run(run())
    return c, seen


@pytest.mark.parametrize("region", ["eu", "jp_1"])
@pytest.mark.parametrize("pw", NASTY)
def test_login_body_is_correctly_urlencoded(region, pw):
    c, seen = _login_request(region, "user@example.com", pw)
    p = const.KINTARO_PROFILES[region]
    expected = urllib.parse.urlencode([
        ("grant_type", "password"), ("username", "user@example.com"), ("password", pw),
        ("client_id", p["client_id"]), ("client_secret", p["client_secret"]),
    ]).encode()
    assert seen["body"] == expected
    assert seen["ctype"] == "application/x-www-form-urlencoded"
    # Rueckrichtung: der Server dekodiert exakt das Passwort
    assert urllib.parse.parse_qs(seen["body"].decode(), keep_blank_values=True)["password"] == [pw]


def test_login_username_with_specials_is_encoded():
    _, seen = _login_request("eu", "a+b&c=d@x.de", "p")
    assert urllib.parse.parse_qs(seen["body"].decode())["username"] == ["a+b&c=d@x.de"]


def test_eu_login_body_without_specials_is_byte_identical_golden():
    _, seen = _login_request("eu", "user@example.com", "secret123")
    assert seen["body"] == (
        b"grant_type=password&username=user%40example.com&password=secret123"
        b"&client_id=" + const.EU_CLIENT_ID.encode() + b"&client_secret=" + const.EU_CLIENT_SECRET.encode()
    )


def test_percent_hash_password_encoded_exactly():
    _, seen = _login_request("jp_1", "u", "pa%ss#word")
    assert b"&password=pa%25ss%23word&" in seen["body"]


# ----------------------------------------------------------------- Timeouts
def test_explicit_timeouts_on_every_client():
    for region in ("eu", "jp_1"):
        t = MitsubishiEUClient("u", "p", "1", region=region)._http.timeout
        assert (t.connect, t.read) == (10.0, 30.0) and t.write == 30.0 and t.pool == 30.0


# ------------------------------------------------- Status mit Mock-Server
KEY = "0123456789abcdef"
VIN = "VIN123"

PAYLOADS = {
    "/status/getVSR/v1": {"data": {"diagnostic": {"odo": {"value": "1234"}}}},
    "/status/getChargeDetails/v1": {"hvBatteryLife": 55, "isCharging": True, "isPluggedIn": True},
    "/status/getClimateDetails/v1": {"isACOn": True, "targetTemperature": 21},
    "/status/getEngineDetails/v1": {"isEngineOn": False},
    "/status/getChargingBaseCost/v1": {"baseCost": "0.3"},
    "/vehicle/getFirmwareStatus/v1": {"installed": [{"version": "9.9"}]},
    "/remote/getVehicleLocation/v1": {"locationLatitude": {"value": 48.4}, "locationLongitude": {"value": 8.1}},
    "/status/getMileageHistory/v1": {"trips": []},
    "/status/getChargingHistory/v1": {"charges": []},
    "/vehicle/getGeofenceAlert/v1": {"data": {"minRad": 1, "maxRad": 2}},
    "/vehicle/getSpeedAlert/v1": {"speedUnit": "kmh"},
}


def _ok(p, payload):
    enc = api_mod._encrypt_body(json.dumps(payload), KEY, p)
    return httpx.Response(200, json={"state": "S", "payload": enc})


def _client(region, behaviour, caplog=None):
    """behaviour(endpoint) -> None (ok) | 'timeout' | ('http', code) | 'junk' | 'reject'"""
    p = const.KINTARO_PROFILES[region]
    calls = []

    def handler(request: httpx.Request):
        ep = request.url.path.removeprefix("/prod")
        calls.append(ep)
        b = behaviour(ep)
        if b == "timeout":
            raise httpx.ReadTimeout("read timed out", request=request)
        if isinstance(b, tuple):
            return httpx.Response(b[1], text="boom")
        if b == "junk":
            return httpx.Response(200, text="<html>nope</html>")
        if b == "reject":
            return httpx.Response(200, json={"state": "F", "errorCode": "E1"})
        return _ok(p, PAYLOADS[ep])

    c = MitsubishiEUClient("user", "SECRETPASSWORD", "", region=region)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=api_mod.HTTP_TIMEOUT)
    c._token = TokenState("TOKENVALUE", "REFRESHVALUE", datetime.now() + timedelta(hours=1))
    c._enc_key, c._sign_key = KEY, "signkey"
    c._internal_vins = {VIN: "IV1"}
    return c, calls


def _status(c):
    async def run():
        try:
            return await c.async_get_vehicle_status(VIN)
        finally:
            await c.async_close()
    return asyncio.run(run())


@pytest.mark.parametrize("region", ["eu", "jp_1"])
@pytest.mark.parametrize("fail", ["timeout", ("http", 503), "junk"])
def test_failing_charge_endpoint_does_not_break_status(region, fail, caplog):
    caplog.set_level(logging.WARNING)
    c, calls = _client(region, lambda ep: fail if ep == "/status/getChargeDetails/v1" else None)
    st = _status(c)
    assert st.odometer == 1234 and st.ac_on is True and st.firmware_version == "9.9"
    assert st.location.latitude == 48.4 and st.speed_alert_unit == "kmh"
    assert st.battery_level is None and st.failed_sources == {"charge"}
    assert "/status/getChargeDetails/v1" in caplog.text and f"Region={c._label}" in caplog.text
    assert any(x in caplog.text for x in ("Timeout", "HTTP 503", "unlesbar"))
    assert "SECRETPASSWORD" not in caplog.text and "TOKENVALUE" not in caplog.text
    assert calls[-1] == "/vehicle/getSpeedAlert/v1"  # Rest wurde noch abgefragt


def test_every_optional_endpoint_can_fail_alone():
    for ep in PAYLOADS:
        c, _ = _client("jp_1", lambda e, ep=ep: "timeout" if e == ep else None)
        st = _status(c)
        assert len(st.failed_sources) == 1, ep


def test_all_endpoints_timing_out_still_returns_state():
    c, _ = _client("jp_1", lambda ep: "timeout")
    st = _status(c)
    assert st.vin == VIN and st.battery_level is None
    assert {"vsr", "charge", "climate", "engine", "cost", "firmware", "mileage",
            "charging_history", "geofence", "speed_alert", "location"} <= st.failed_sources


def test_clean_server_rejection_is_not_marked_failed(caplog):
    caplog.set_level(logging.WARNING)
    c, _ = _client("eu", lambda ep: "reject" if ep == "/vehicle/getSpeedAlert/v1" else None)
    st = _status(c)
    assert st.failed_sources == set()
    assert "errorCode=E1" in caplog.text and "HTTP 200" in caplog.text


def test_time_budget_skips_remaining_endpoints(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(api_mod, "STATUS_BUDGET_S", -1.0)
    c, calls = _client("jp_1", lambda ep: None)
    st = _status(c)
    assert calls == []  # nichts mehr angefragt
    assert "Zeitbudget" in caplog.text and "vsr" in st.failed_sources


def test_vehicle_list_failure_returns_empty_so_setup_aborts():
    c, _ = _client("jp_1", lambda ep: "timeout")
    async def run():
        try:
            return await c.async_get_vehicles()
        finally:
            await c.async_close()
    assert asyncio.run(run()) == []  # __init__ -> ConfigEntryNotReady


def test_login_timeout_returns_false_with_log(caplog):
    caplog.set_level(logging.WARNING)
    def handler(request):
        raise httpx.ConnectTimeout("c", request=request)
    async def run():
        c = MitsubishiEUClient("u", "SECRETPASSWORD", "1", region="jp_1")
        c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=api_mod.HTTP_TIMEOUT)
        try:
            return await c.async_login()
        finally:
            await c.async_close()
    assert asyncio.run(run()) is False
    assert "oauth/token(login)" in caplog.text and "Region=jp_1" in caplog.text and "Timeout" in caplog.text
    assert "SECRETPASSWORD" not in caplog.text


# ----------------------------------------------------------------- Debug-Log
def _own(caplog):
    """Nur unsere Log-Zeilen (httpx loggt selbst die URL; HA setzt diesen Logger auf WARNING)."""
    return "\n".join(r.getMessage() for r in caplog.records
                     if r.name.startswith("mitsubishi_outlander_phev_eu"))


def test_debug_log_has_method_endpoint_region_status_duration_and_no_secrets(caplog):
    caplog.set_level(logging.DEBUG)
    c, _ = _client("jp_1", lambda ep: None)
    _status(c)
    assert re.search(r"GET /status/getVSR/v1 \[Region=jp_1 \(Variante 1\)\] -> HTTP 200 in \d+ ms", _own(caplog))
    assert re.search(r"POST /remote/getVehicleLocation/v1 \[Region=jp_1 \(Variante 1\)\] -> HTTP 200 in \d+ ms", _own(caplog))
    for secret in ("SECRETPASSWORD", "TOKENVALUE", "REFRESHVALUE", KEY, "signkey", "params="):
        assert secret not in _own(caplog)


def test_debug_log_login_has_no_password(caplog):
    caplog.set_level(logging.DEBUG)
    _login_request("eu", "u", "SECRETPASSWORD")
    assert "POST oauth/token(login) [Region=eu] -> HTTP 401 in" in _own(caplog)
    assert "SECRETPASSWORD" not in _own(caplog) and const.EU_CLIENT_SECRET not in _own(caplog)


def test_readme_documents_debug_logging():
    txt = (_PKG.parents[1] / "README.md").read_text(encoding="utf-8")
    assert "custom_components.mitsubishi_outlander_phev_eu: debug" in txt


# ------------------------------------------------------------ V3 entfernt
def test_jp3_not_selectable_but_old_entries_fall_back_to_jp1(caplog):
    caplog.set_level(logging.INFO)
    assert "jp_3" not in const.REGIONS and "jp_3" not in const.KINTARO_PROFILES
    data = {"username": "u", "password": "p", "pin": "1", "region": "jp_3"}
    assert factory.get_region(data) == "jp_1"
    c = factory.create_client(data)
    assert isinstance(c, MitsubishiEUClient) and c._p is const.KINTARO_PROFILES["jp_1"]
    assert "jp_3" in caplog.text and "jp_1" in caplog.text


def test_config_flow_dropdown_has_no_jp3_and_maps_old_entry():
    src = (_PKG / "config_flow.py").read_text(encoding="utf-8")
    assert "REGION_JP_3" not in src and "options=REGIONS" in src
    # _selectable_region -> get_region -> jp_1 (Dropdown-Wert existiert)
    assert factory.get_region({"region": "jp_3"}) in const.REGIONS


# ------------------------------------------------------ Entity-Verfuegbarkeit
def test_entity_source_covers_known_keys_only():
    keys = set()
    for f in ("sensor.py", "binary_sensor.py"):
        keys |= set(re.findall(r'^\s+key="([a-z_0-9]+)"', (_PKG / f).read_text(encoding="utf-8"), re.M))
    assert set(const.ENTITY_SOURCE) <= keys
    assert keys - set(const.ENTITY_SOURCE) == set()  # jede Entity hat eine Quelle
    assert set(const.ENTITY_SOURCE.values()) <= {
        "vsr", "charge", "climate", "engine", "cost", "firmware", "mileage", "charging_history"}
