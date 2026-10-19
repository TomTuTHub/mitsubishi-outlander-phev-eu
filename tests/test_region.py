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


# ---------------------------------------------------------------- JP region
from mitsubishi_outlander_phev_eu import api as api_mod  # noqa: E402
from mitsubishi_outlander_phev_eu import const  # noqa: E402


def test_jp_region_selects_kintaro_client_with_jp_profile():
    c = factory.create_client({**CREDS, "region": "jp"})
    assert isinstance(c, MitsubishiEUClient)
    assert c._p["auth_url"] == "https://idm.prod.goa.mitsubishi-motors.com/oauth/token"
    assert c._p["kintaro_base"] == "https://kintaro.prod.goa.mitsubishi-motors.com/prod"
    assert c._p["client_id"] == "Rn6WysiaR7xDrz39If3d3foQsuHLAjiw"
    assert c._p["app_code"] == "202411201314294614109"
    assert c._p["jwt_sign"] == "w0kJJQTMZgxFboq4sduXIsOcJwRaTjUI"


def test_eu_profile_unchanged():
    p = factory.create_client(CREDS)._p
    assert p["auth_url"] == const.EU_AUTH_URL and p["client_id"] == const.EU_CLIENT_ID
    assert p["app_code"] == "202501100700475534942"
    assert p["jwt_sign"] == "dh7RqD9qTgRwqlHaidv3hYLP0BicgkR9"
    assert p["client_secret"] == const.EU_CLIENT_SECRET


def test_regions_listed():
    assert const.REGIONS == ["eu", "us", "jp"]


def test_jp_login_and_init_use_jp_urls():
    async def run(region):
        c = MitsubishiEUClient("u", "p", "1", region=region)
        urls, forms, hdrs = [], [], []
        class R:
            status_code = 200
            def json(self): return {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
        class H:
            async def post(self, url, **kw):
                urls.append(url); forms.append(kw.get("data")); hdrs.append(kw.get("headers"))
                return R()
        c._http = H()
        async def fake_init(): return True
        c._kintaro_init = fake_init
        await c.async_login()
        # init step: only URL/header selection, then stop at the response
        c2 = MitsubishiEUClient("u", "p", "1", region=region)
        c2._http = H(); c2._token.access_token = "a"
        class R2:
            status_code = 200
            def json(self): return {"code": "x"}
        class H2:
            async def post(self, url, **kw):
                urls.append(url); hdrs.append(kw["headers"]); return R2()
        c2._http = H2()
        await c2._kintaro_init()
        return urls, forms, hdrs
    for region, auth, base, app in [
        ("eu", const.EU_AUTH_URL, const.EU_KINTARO_BASE, const.KINTARO_APP_CODE),
        ("jp", "https://idm.prod.goa.mitsubishi-motors.com/oauth/token",
         "https://kintaro.prod.goa.mitsubishi-motors.com/prod", "202411201314294614109"),
    ]:
        urls, forms, hdrs = asyncio.run(run(region))
        assert urls[0] == auth
        assert urls[1] == base + "/service/checkVersion"
        assert forms[0]["client_id"] == const.KINTARO_PROFILES[region]["client_id"]
        assert hdrs[1]["knt-app-key"] == app


def test_sign_depends_on_region_but_eu_default_is_stable():
    n = "1700000000000"
    eu = api_mod._compute_init_sign(n)
    assert eu == api_mod._compute_init_sign(n, const.KINTARO_PROFILES["eu"])
    assert eu != api_mod._compute_init_sign(n, const.KINTARO_PROFILES["jp"])  # app_code differs
