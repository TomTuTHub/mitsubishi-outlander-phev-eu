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
    assert const.REGIONS == ["eu", "jp_1", "jp_2"]
    assert "us" not in const.REGIONS


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


# ------------------------------------------------- JP values from the APK
import base64 as _b64  # noqa: E402
import hashlib  # noqa: E402
from Crypto.Cipher import AES  # noqa: E402
from Crypto.Util.Padding import pad  # noqa: E402

_NONCE = "1700000000000"


def _decode_security_key(hex_tail: str) -> str:
    """Kintaro security_key_settings tail: XOR with sha256(sha256(pkg)) hex, then ROT47."""
    pkg = b"com.mitsubishi_motors.mitsubishimotors"
    k = hashlib.sha256(hashlib.sha256(pkg).hexdigest().encode()).hexdigest().encode()
    x = bytes(c ^ k[i % len(k)] for i, c in enumerate(bytes.fromhex(hex_tail)))
    return bytes(33 + ((c - 33 + 47) % 94) if 33 <= c <= 126 else c for c in x).decode()


def test_eu_signing_output_byte_identical_to_pre_jp_code():
    """Golden values taken from the code before kt_cfg was introduced."""
    assert api_mod._compute_init_sign(_NONCE) == \
        "DDE3FB9BB1AAD6B607613FE18662B240F5AA6CCBD6D963731BBEF83F64B22827"
    assert api_mod._compute_sign("BODY", _NONCE, "SK") == \
        "0C562A8D18522F8DDD7A6C23087E4709F594265ABF5FB209B1C175316774707A"
    assert api_mod._encrypt_body("{}", "0123456789abcdef") == "8myzm12AtJCPT4dV7hVcNQ=="


def test_security_key_decoding_reproduces_eu_and_gives_jp():
    # EU: decoding the APK value reproduces the key that was already in use
    assert _decode_security_key("56070356505d5054520450555f045604") == const.KINTARO_SECURITY_KEY
    # JP: same decoding applied to the JP APK value
    assert _decode_security_key("50003969030e523e5407050159575d50") == \
        const.KINTARO_PROFILES["jp"]["security_key"] == "ba001f70172d159e"


def test_jp_profile_values_from_apk():
    p = const.KINTARO_PROFILES["jp"]
    assert p["pkg_name"] == "com.mitsubishi_motors.mitsubishimotors"
    assert p["hash"] == "EF453267190EA26C4B0A3EBE65E3F391"
    assert (p["knt_region"], p["locale"], p["language"], p["app_version"]) == \
        ("JP", "ja-JP", "ja", "3.1.0")
    assert p["kt_cfg"] == (13, 29, 1, 28, 8, 13, 7, 10, 3, 3)
    assert const.KINTARO_PROFILES["eu"]["kt_cfg"] == (15, 31, 18, 22, 0, 13, 1, 5, 7, 7)
    assert all(len(v) == 10 for v in (p["kt_cfg"], const.KINTARO_PROFILES["eu"]["kt_cfg"]))
    assert p["kt_cfg"][1] - p["kt_cfg"][0] == 16  # AES-128 key slice


def test_jp_crypto_uses_jp_slices():
    p = const.KINTARO_PROFILES["jp"]
    m2 = api_mod._md5_2(p)
    # AES key slice [13:29] and IV from the JP security key
    key = m2[13:29].encode()
    payload = _b64.b64encode(AES.new(key, AES.MODE_CBC, p["security_key"].encode()).encrypt(
        pad(b'{"ok":1}', 16))).decode()
    assert api_mod._decrypt_init_response(payload, p) == {"ok": 1}
    # init signature: nonce offset 3, slices [1:28]+[8:13]+[7:10]
    asm = m2[1:28] + m2[8:13] + m2[7:10]
    ns = _NONCE[3:]
    assert api_mod._compute_init_sign(_NONCE, p) == \
        hashlib.sha256((_NONCE + ns + ns + asm).encode()).hexdigest().upper()
    assert api_mod._compute_sign("B", _NONCE, "K", p) == \
        hashlib.sha256(("B" + _NONCE + ns + ns + "K").encode()).hexdigest().upper()
    assert api_mod._compute_init_sign(_NONCE, p) != api_mod._compute_init_sign(_NONCE)


def test_jp_headers_follow_app_and_eu_headers_unchanged():
    jp = factory.create_client({**CREDS, "region": "jp"})._kintaro_headers("1", "s")
    assert jp["knt-region"] == "JP" and jp["knt-user-country"] == "JP"
    assert jp["knt-region-code"] == "jp" and jp["knt-iso-locale"] == "ja-JP"
    assert jp["knt-app-version"] == "3.1.0" and jp["knt-language"] == "ja"
    assert jp["knt-timezone"] == "Asia/Tokyo"
    assert jp["knt-app-unique-id"] == "com.mitsubishi_motors.mitsubishimotors"
    eu = factory.create_client(CREDS)._kintaro_headers("1", "s")
    assert "knt-user-country" not in eu and "knt-region-code" not in eu
    assert eu["knt-region"] == "DE" and eu["knt-app-version"] == "1.3.1"


# ------------------------------------------- JP-Varianten, US weg, Diagnose
import json  # noqa: E402
import logging  # noqa: E402


def test_us_not_selectable_nor_translated():
    pkg = _PKG
    for f in ("strings.json", "translations/en.json", "translations/de.json"):
        opts = json.loads((pkg / f).read_text())["selector"]["region"]["options"]
        assert list(opts) == const.REGIONS and "us" not in opts
        assert "United States" not in json.dumps(opts) and "USA" not in json.dumps(opts)


def test_option_labels_match_regions():
    for f, word in (("strings.json", "Variant"), ("translations/en.json", "Variant"),
                    ("translations/de.json", "Variante")):
        opts = json.loads((_PKG / f).read_text())["selector"]["region"]["options"]
        for n in (1, 2):
            assert opts[f"jp_{n}"] == f"Japan / Thailand – {word} {n} (" + \
                ("experimentell" if word == "Variante" else "experimental") + ")"


def test_two_variants_differ_only_where_intended():
    P = const.KINTARO_PROFILES
    v1, v2 = P["jp_1"], P["jp_2"]
    assert "jp_3" not in P
    assert P["jp"] is v1  # alter Eintrag "jp" == Variante 1
    shared = ("auth_url", "kintaro_base", "client_id", "client_secret", "app_code",
              "jwt_sign", "pkg_name", "hash", "security_key", "kt_cfg", "timezone")
    for k in shared:
        assert v1[k] == v2[k]
    assert "omit_headers" not in v1 and "kt_slice_mode" not in v1
    assert v2["omit_headers"] == ("knt-region",) and "kt_slice_mode" not in v2
    for n in ("jp_1", "jp_2", "jp"):
        assert isinstance(factory.create_client({**CREDS, "region": n}), MitsubishiEUClient)


def test_variant_headers_and_signature():
    h = {n: factory.create_client({**CREDS, "region": n})._kintaro_headers("1", "s")
         for n in ("jp_1", "jp_2")}
    assert h["jp_1"]["knt-region"] == "JP"
    assert "knt-region" not in h["jp_2"]
    assert h["jp_2"]["knt-region-code"] == "jp" and h["jp_2"]["knt-user-country"] == "JP"
    P = const.KINTARO_PROFILES
    s1, s2 = (api_mod._compute_init_sign(_NONCE, P[n]) for n in ("jp_1", "jp_2"))
    assert s1 == s2


def test_eu_signature_unaffected_by_slice_mode():
    assert "kt_slice_mode" not in const.KINTARO_PROFILES["eu"]
    assert api_mod._compute_init_sign(_NONCE) == \
        "DDE3FB9BB1AAD6B607613FE18662B240F5AA6CCBD6D963731BBEF83F64B22827"
    assert "knt-region" in factory.create_client(CREDS)._kintaro_headers("1", "s")


def test_snippet_is_truncated_and_secret_free():
    secret = "A" * 60
    txt = ('{"access_token":"abc.def","refresh_token":"r","password":"hunter2","payload":"%s",'
           '"error":"x"}' % secret) + " pad" * 100
    out = api_mod._safe_snippet(txt)
    assert len(out) <= 203
    for bad in ("abc.def", "hunter2", secret):
        assert bad not in out
    assert '"error":"x"' in out
    assert api_mod._safe_snippet("") == ""


class _Resp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text
    def json(self):
        return json.loads(self.text)


def _run_login(region, resp, caplog):
    c = MitsubishiEUClient("u", "SECRETPW", "1", region=region)
    class H:
        async def post(self, url, **kw): return resp
    c._http = H()
    caplog.set_level(logging.ERROR)
    return asyncio.run(c.async_login())


def test_login_failure_logs_full_status_region_and_body(caplog):
    body = '{"error":"invalid_grant","error_description":"bad creds","access_token":"LEAKME"}'
    assert _run_login("jp_2", _Resp(403, body), caplog) is False
    msg = caplog.text
    assert "HTTP 403" in msg and "jp_2 (Variante 2)" in msg and "invalid_grant" in msg
    assert "LEAKME" not in msg and "SECRETPW" not in msg


def test_login_failure_eu_logs_region(caplog):
    assert _run_login("eu", _Resp(401, "nope"), caplog) is False
    assert "HTTP 401" in caplog.text and "Region=eu" in caplog.text


def test_init_failure_logs_status_and_truncates(caplog):
    c = MitsubishiEUClient("u", "p", "1", region="jp_2")
    class H:
        async def post(self, url, **kw):
            return _Resp(400, json.dumps({"state": "F", "errorCode": "40012", "msg": "x" * 500}))
    c._http = H()
    caplog.set_level(logging.ERROR)
    assert asyncio.run(c._kintaro_init()) is False
    assert "HTTP 400" in caplog.text and "jp_2 (Variante 2)" in caplog.text
    assert "40012" in caplog.text and "x" * 300 not in caplog.text


def test_init_non_json_response_is_logged(caplog):
    c = MitsubishiEUClient("u", "p", "1", region="jp_1")
    class H:
        async def post(self, url, **kw): return _Resp(502, "<html>Bad Gateway</html>")
    c._http = H()
    caplog.set_level(logging.ERROR)
    assert asyncio.run(c._kintaro_init()) is False
    assert "HTTP 502" in caplog.text and "Bad Gateway" in caplog.text


# ---- Punkt 4: bestehende EU-Eintraege (ohne region-Feld) -------------------
def test_existing_entry_data_without_region_runs_as_eu():
    legacy = {"username": "u", "password": "p", "pin": "1234", "update_interval": 15}
    assert factory.get_region(legacy) == "eu"
    c = factory.create_client(legacy)
    assert c._p is const.KINTARO_PROFILES["eu"] and c._label == "eu"
    assert factory.get_region({**legacy, "region": None}) == "eu"
    # Signatur + Header wie vor der Region-Funktion (Golden Values oben)
    assert c._p["kt_cfg"] == (15, 31, 18, 22, 0, 13, 1, 5, 7, 7)
    assert c._kintaro_headers("1", "s")["knt-region"] == "DE"
    assert const.DEFAULT_REGION == "eu"


def test_config_flow_source_has_no_forced_region_write():
    """Der Flow darf bestehende Eintraege nicht anfassen (kein Migration-Schreibzugriff noetig)."""
    src = (_PKG / "config_flow.py").read_text()
    assert "async_migrate_entry" not in src
    init = (_PKG / "__init__.py").read_text()
    assert "create_client(entry.data)" in init  # Region nur gelesen, nie veraendert
