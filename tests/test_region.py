"""Offline tests for region selection and the US client (no network, no HA)."""
import asyncio
import base64
import sys
from pathlib import Path

import types  # noqa: E402

# The package __init__ imports Home Assistant, which is not installed here.
# Register an empty stand-in package so that only the pure-Python modules load.
_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
_stub = types.ModuleType("mitsubishi_outlander_phev_eu")
_stub.__path__ = [str(_PKG)]
sys.modules["mitsubishi_outlander_phev_eu"] = _stub

from mitsubishi_outlander_phev_eu import api_us, client as factory  # noqa: E402
from mitsubishi_outlander_phev_eu.api import MitsubishiEUClient  # noqa: E402
from mitsubishi_outlander_phev_eu.api_us import MitsubishiUSClient  # noqa: E402

CREDS = {"username": "u", "password": "p", "pin": "1234"}

VEHICLESTATE = {
    "vin": "V", "ts": "2024-03-14T12:34:56.789Z",
    "state": {"extLocMap": {"lon": 8.1, "lat": 48.4, "ts": "1"},
              "ignitionState": "1",
              "chargingControl": {"cruisingRangeCombined": "200"}},
}
STATUS = {"vhr": [{"dt": {
    "diagnostic": {
        "odo": {"displayMessage": "odo_miles", "value": "100"},
        "spd": {"displayMessage": "vehicle_speed", "value": "10"},
        "availRange": {"displayMessage": "availRange_miles", "value": "--"},
        "breakWarn": {"warning": True}, "engineOilWarn": {"warning": False}},
    "vehicleStatus": {
        "doorStatus": {"doors": [
            {"position": {"displayMessage": "doorTrunk"}, "state": {"value": "1"}},
            {"position": {"displayMessage": "doorHood"}, "state": {"value": "0"}}]},
        "lightStatus": {"lights": [
            {"position": {"displayMessage": "lightHead"}, "state": {"value": "3"}}]}}}}]}


def test_missing_region_means_eu():
    """Existing entries have no region key -> EU, no migration needed."""
    assert factory.get_region(CREDS) == "eu"
    assert isinstance(factory.create_client(CREDS), MitsubishiEUClient)
    assert isinstance(factory.create_client({**CREDS, "region": "eu"}), MitsubishiEUClient)


def test_us_region_selects_us_client():
    assert isinstance(factory.create_client({**CREDS, "region": "us"}), MitsubishiUSClient)


def test_pin_hash_matches_reference_vector():
    cn = base64.b64encode(b"c" * 32).decode()
    sn = base64.b64encode(b"s" * 32).decode()
    h = api_us.generate_pin_hash(cn, sn, "1234")
    assert h and len(base64.b64decode(h)) == 16
    assert h == api_us.generate_pin_hash(cn, sn, "1234")
    assert h != api_us.generate_pin_hash(cn, sn, "1235")
    # value produced by the upstream mitsubishi_connect_client reference code
    assert h == "CNFYGwRK/ylRKZS50guD7A=="


def test_us_parsing_converts_miles_and_maps_fields():
    async def run():
        c = MitsubishiUSClient("u", "p", "1")
        async def fake_token(): return True
        async def fake_req(method, url, **kw):
            return VEHICLESTATE if url.endswith("/vehiclestate") else STATUS
        c._ensure_token = fake_token
        c._request = fake_req
        return await c.async_get_vehicle_status("V")
    s = asyncio.run(run())
    assert s.odometer == 160.9 and s.speed == 16.1
    assert s.total_range == 200.0  # "--" availRange ignored
    assert s.engine_on and s.brake_warning and not s.engine_oil_warning
    assert s.door_trunk_open and not s.door_hood_open and not s.headlights_on
    assert (s.location.latitude, s.location.longitude) == (48.4, 8.1)
    assert s.battery_level is None


def test_us_unsupported_commands_report_code():
    c = MitsubishiUSClient("u", "p", "1")
    assert asyncio.run(c.async_horn("V")) is False
    assert c.last_error_code == "unsupported_in_region"


def test_us_login_stores_token():
    async def run():
        c = MitsubishiUSClient("u", "p", "1")
        calls = []
        async def fake_req(method, url, **kw):
            calls.append((url, kw.get("data")))
            return {"access_token": "a", "refresh_token": "r",
                    "expires_in": 3600, "accountDN": "dn"}
        c._request = fake_req
        return await c.async_login(), c, calls
    ok, c, calls = asyncio.run(run())
    assert ok and c._account_dn == "dn"
    assert calls[0][0].endswith("/auth/v1/token")
    assert calls[0][1]["grant_type"] == "password"
