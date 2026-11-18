"""Offline tests v1.1.0b6: neuer IDM-Login (EU) und JP-Fallback bei unauthorized_client.

Mitsubishi hat am 10.11.2026 den EU-Login per password grant abgeschaltet. EU nutzt
nur noch /api/v1/init + /api/v1/login + /api/v1/refreshToken (wie v1.0.8 / App 3.2.0).
JP bleibt beim password grant und wechselt nur bei "unauthorized_client" genau EINMAL.

Keine Netzwerkzugriffe: httpx laeuft ueber MockTransport.
"""
import asyncio
import base64
import json
import sys
import types
import urllib.parse
from pathlib import Path

import httpx
import pytest
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
if "mitsubishi_outlander_phev_eu" not in sys.modules:
    _stub = types.ModuleType("mitsubishi_outlander_phev_eu")
    _stub.__path__ = [str(_PKG)]
    sys.modules["mitsubishi_outlander_phev_eu"] = _stub

from mitsubishi_outlander_phev_eu import api  # noqa: E402
from mitsubishi_outlander_phev_eu import const  # noqa: E402

EU = const.KINTARO_PROFILES["eu"]
JP = const.KINTARO_PROFILES["jp_1"]
EU_HOST = "idm.prod.goa-eu.mitsubishi-motors.com"
JP_HOST = "idm.prod.goa.mitsubishi-motors.com"

_RSA = RSA.generate(1024)
PUB_B64 = base64.b64encode(_RSA.publickey().export_key(format="DER")).decode()

OK_LOGIN = {"code": "200", "data": {"accessToken": "AT", "refreshToken": "RT", "expiresIn": 7200}}


def _decrypt_pw(value: str) -> tuple[str, str]:
    idx, b64 = value.split("@", 1)
    return idx, PKCS1_v1_5.new(_RSA).decrypt(base64.b64decode(b64), None).decode()


class FakeServer:
    """Beide Login-Wege: /oauth/token (form) und IDM /api/v1/* (verschluesselt)."""

    def __init__(self, oauth=(200, {"access_token": "OAT", "refresh_token": "ORT", "expires_in": 3600}),
                 init=None, login=OK_LOGIN, refresh=None, oauth_exc=None):
        self.oauth, self.init, self.login, self.refresh = oauth, init, login, refresh
        self.oauth_exc = oauth_exc
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth/token":
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            self.calls.append({"host": request.url.host, "path": path, "body": form,
                               "headers": dict(request.headers)})
            if self.oauth_exc:
                raise self.oauth_exc("x", request=request)
            status, body = self.oauth
            if form.get("grant_type") == "refresh_token" and isinstance(self.refresh, tuple):
                status, body = self.refresh
            return httpx.Response(status, json=body)
        body = json.loads(api._idm_decrypt(json.loads(request.content)["payload"]))
        self.calls.append({"host": request.url.host, "path": path, "body": body,
                           "headers": dict(request.headers)})
        answer = {
            "/api/v1/init": self.init or {"code": "200", "data": {"keyIndex": "K1", "publicKey": PUB_B64}},
            "/api/v1/login": self.login,
            "/api/v1/refreshToken": self.refresh if isinstance(self.refresh, dict) else {"code": "401"},
        }.get(path, {"code": "404"})
        return httpx.Response(200, json={"payload": api._idm_encrypt(json.dumps(answer))})

    @property
    def paths(self):
        return [c["path"] for c in self.calls]


def _client(region, server, username="u@x.de", password="pw-1"):
    c = api.MitsubishiEUClient(username, password, "1234", region=region)
    c.kintaro_calls = 0

    async def fake_kintaro_init():
        c.kintaro_calls += 1
        return True

    c._kintaro_init = fake_kintaro_init
    return c


def _run(region, server, action="login", setup=None, **kw):
    async def run():
        c = _client(region, server, **kw)
        await c._http.aclose()
        c._http = httpx.AsyncClient(transport=httpx.MockTransport(server.handler))
        if setup:
            setup(c)
        try:
            if action == "login":
                res = await c.async_login()
            elif action == "login_twice":
                res = (await c.async_login(), await c.async_login())
            else:
                res = await c.async_refresh_token()
            return res, c
        finally:
            await c.async_close()
    return asyncio.run(run())


# ------------------------------------------------------------------ Helfer (aus v1.0.8)
def test_payload_roundtrip():
    s = json.dumps({"a": 1, "ü": "ß"})
    assert api._idm_decrypt(api._idm_encrypt(s)) == s


def test_password_rsa_keyindex():
    assert _decrypt_pw(api._idm_encrypt_password("geheim!1", PUB_B64, "k9")) == ("k9", "geheim!1")


def test_device_id_stable_per_user():
    assert api._idm_device_id("a@b.de") == api._idm_device_id("a@b.de")
    assert api._idm_device_id("a@b.de") != api._idm_device_id("c@b.de")
    assert len(api._idm_device_id("a@b.de")) == 16


def test_eu_idm_headers_byte_identical_to_v108():
    """Golden: exakt der Header-Satz von v1.0.8 (main, adf9904)."""
    h = api._idm_headers("dev1", EU, ts="1700000000000", nonce="n-1")
    assert h == {
        "Content-Type": "application/json",
        "User-Agent": "okhttp/4.12.0",
        "X-Device-Id": "dev1",
        "X-Locale": "en-GB",
        "X-Timezone": "1",
        "X-App-Name": "Mitsubishi Motors",
        "X-App-Version": "3.2.0",
        "X-App-Unique-Id": "com.mitsubishi_motors.mitsubishimotors",
        "X-OS-Type": "android",
        "X-OS-Version": "14",
        "X-Timestamp": "1700000000000",
        "X-Encrypt-Payload": "true",
        "X-Client-Id": const.EU_CLIENT_ID,
        "X-Client-Secret": const.EU_CLIENT_SECRET,
        "X-Nonce": "n-1",
        "X-Signature": api._md5h(const.EU_CLIENT_ID + "n-1" + "1700000000000"),
    }
    assert api._idm_headers("dev1", ts="1", nonce="n") == api._idm_headers("dev1", EU, ts="1", nonce="n")


def test_eu_device_id_same_formula_as_v108():
    assert api._idm_device_id("u@x.de") == api._sha256h("ha-outlander-phev-eu:u@x.de")[:16]


# ------------------------------------------------------------------ EU: nur neuer Login
def test_eu_login_uses_idm_only_never_oauth():
    srv = FakeServer()
    ok, c = _run("eu", srv)
    assert ok is True
    assert srv.paths == ["/api/v1/init", "/api/v1/login"]
    assert {x["host"] for x in srv.calls} == {EU_HOST}
    lb = srv.calls[1]["body"]
    assert set(lb) == {"username", "password", "clientId", "deviceId"}
    assert lb["clientId"] == const.EU_CLIENT_ID and lb["username"] == "u@x.de"
    assert _decrypt_pw(lb["password"]) == ("K1", "pw-1")
    assert srv.calls[0]["body"] == {"deviceId": lb["deviceId"], "clientId": const.EU_CLIENT_ID}
    assert c._token.access_token == "AT" and c._token.refresh_token == "RT"
    assert c.kintaro_calls == 1


def test_eu_profile_has_no_password_grant():
    assert EU["login"] == const.LOGIN_IDM and "auth_url" not in EU
    assert not hasattr(const, "EU_AUTH_URL")


def test_eu_login_rejected_exactly_one_attempt():
    srv = FakeServer(login={"code": "401", "message": "wrong"})
    ok, c = _run("eu", srv)
    assert ok is False
    assert srv.paths == ["/api/v1/init", "/api/v1/login"]
    assert c.kintaro_calls == 0


def test_eu_init_failure_stops_before_login():
    srv = FakeServer(init={"code": "500"})
    ok, _ = _run("eu", srv)
    assert ok is False and srv.paths == ["/api/v1/init"]


def test_eu_refresh_uses_refresh_endpoint_keeps_old_rt():
    srv = FakeServer(refresh={"code": "200", "data": {"accessToken": "AT2", "expiresIn": 7200}})
    ok, c = _run("eu", srv, action="refresh",
                 setup=lambda c: setattr(c, "_token", api.TokenState(access_token="AT", refresh_token="RT")))
    assert ok is True
    assert srv.paths == ["/api/v1/refreshToken"]
    assert srv.calls[0]["body"] == {"clientId": const.EU_CLIENT_ID,
                                    "clientSecret": const.EU_CLIENT_SECRET, "refreshToken": "RT"}
    assert c._token.access_token == "AT2" and c._token.refresh_token == "RT"


def test_eu_refresh_rejected_falls_back_to_login():
    srv = FakeServer(refresh={"code": "401"})
    ok, c = _run("eu", srv, action="refresh",
                 setup=lambda c: setattr(c, "_token", api.TokenState(access_token="AT", refresh_token="RT")))
    assert ok is True
    assert srv.paths == ["/api/v1/refreshToken", "/api/v1/init", "/api/v1/login"]
    assert "/oauth/token" not in srv.paths


# ------------------------------------------------------------------ JP: alter Weg + 1 Fallback
def test_jp_default_uses_old_password_grant():
    srv = FakeServer()
    ok, c = _run("jp_1", srv)
    assert ok is True
    assert srv.paths == ["/oauth/token"]
    assert srv.calls[0]["host"] == JP_HOST
    assert srv.calls[0]["body"] == {"grant_type": "password", "username": "u@x.de", "password": "pw-1",
                                    "client_id": JP["client_id"], "client_secret": JP["client_secret"]}
    assert c._use_idm is False and c._token.access_token == "OAT"


def test_jp_legacy_alias_jp_also_old_flow():
    srv = FakeServer()
    ok, _ = _run("jp", srv)
    assert ok is True and srv.paths == ["/oauth/token"]


def test_jp_unauthorized_client_exactly_one_fallback_to_new_login():
    srv = FakeServer(oauth=(400, {"error": "unauthorized_client",
                                  "error_description": "Unauthorized grant type: password"}))
    ok, c = _run("jp_1", srv)
    assert ok is True
    assert srv.paths == ["/oauth/token", "/api/v1/init", "/api/v1/login"]
    assert {x["host"] for x in srv.calls} == {JP_HOST}
    init, login = srv.calls[1], srv.calls[2]
    assert init["body"]["clientId"] == JP["client_id"] == login["body"]["clientId"]
    assert login["headers"]["x-client-id"] == JP["client_id"]
    assert login["headers"]["x-client-secret"] == JP["client_secret"]
    assert login["headers"]["x-app-version"] == "3.1.0"
    assert login["headers"]["x-locale"] == "ja-JP"
    assert _decrypt_pw(login["body"]["password"]) == ("K1", "pw-1")
    assert c._use_idm is True and c._token.access_token == "AT" and c.kintaro_calls == 1


def test_jp_fallback_also_when_body_is_not_json():
    srv = FakeServer()

    def handler(request):
        if request.url.path == "/oauth/token":
            srv.calls.append({"host": request.url.host, "path": "/oauth/token", "body": {}, "headers": {}})
            return httpx.Response(400, text="error=unauthorized_client")
        return FakeServer.handler(srv, request)
    srv.handler = handler
    ok, _ = _run("jp_1", srv)
    assert ok is True and srv.paths == ["/oauth/token", "/api/v1/init", "/api/v1/login"]


def test_jp_fallback_fails_then_error_no_loop():
    srv = FakeServer(oauth=(400, {"error": "unauthorized_client"}),
                     login={"code": "401", "message": "wrong"})
    ok, c = _run("jp_1", srv)
    assert ok is False
    assert srv.paths == ["/oauth/token", "/api/v1/init", "/api/v1/login"]  # genau 1 Umschaltversuch
    assert c._use_idm is False and c.kintaro_calls == 0


def test_jp_fallback_per_login_at_most_once_over_two_logins():
    """Zwei Logins nacheinander, IDM lehnt ab: je Login hoechstens 1 Umschaltversuch."""
    srv = FakeServer(oauth=(400, {"error": "unauthorized_client"}), login={"code": "401"})
    (ok1, ok2), _ = _run("jp_1", srv, action="login_twice")
    assert (ok1, ok2) == (False, False)
    assert srv.paths == ["/oauth/token", "/api/v1/init", "/api/v1/login"] * 2


def test_jp_after_successful_fallback_next_login_goes_straight_to_idm():
    srv = FakeServer(oauth=(400, {"error": "unauthorized_client"}))
    (ok1, ok2), c = _run("jp_1", srv, action="login_twice")
    assert ok1 and ok2
    assert srv.paths == ["/oauth/token", "/api/v1/init", "/api/v1/login", "/api/v1/init", "/api/v1/login"]


@pytest.mark.parametrize("status,body", [
    (400, {"error": "invalid_grant", "error_description": "Bad credentials"}),  # falsches Passwort
    (401, {"error": "invalid_client"}),
    (401, {"error": "x"}),
    (403, {"error": "access_denied"}),
    (500, {"error": "server_error"}),
    (502, None),
])
def test_jp_other_errors_no_fallback(status, body):
    srv = FakeServer(oauth=(status, body))
    ok, c = _run("jp_1", srv)
    assert ok is False
    assert srv.paths == ["/oauth/token"]
    assert c._use_idm is False


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout])
def test_jp_network_errors_no_fallback(exc):
    srv = FakeServer(oauth_exc=exc)
    ok, _ = _run("jp_1", srv)
    assert ok is False and srv.paths == ["/oauth/token"]


def test_jp_refresh_stays_on_old_flow():
    srv = FakeServer()
    ok, c = _run("jp_1", srv, action="refresh",
                 setup=lambda c: setattr(c, "_token", api.TokenState(access_token="A", refresh_token="R")))
    assert ok is True
    assert srv.paths == ["/oauth/token"]
    assert srv.calls[0]["body"]["grant_type"] == "refresh_token"


def test_jp_refresh_unauthorized_client_relogin_with_one_fallback():
    srv = FakeServer(oauth=(400, {"error": "unauthorized_client"}))
    srv.refresh = (400, {"error": "unauthorized_client"})
    ok, c = _run("jp_1", srv, action="refresh",
                 setup=lambda c: setattr(c, "_token", api.TokenState(access_token="A", refresh_token="R")))
    assert ok is True
    assert srv.paths == ["/oauth/token", "/oauth/token", "/api/v1/init", "/api/v1/login"]
    assert [c_["body"].get("grant_type") for c_ in srv.calls[:2]] == ["refresh_token", "password"]


def test_jp_profile_idm_values_from_jp_profile():
    assert JP["login"] == const.LOGIN_LEGACY and JP["idm_fallback"] is True
    assert JP["idm_base"] == "https://" + JP_HOST
    assert JP["auth_url"].startswith(JP["idm_base"] + "/")
    assert JP["client_id"] != const.EU_CLIENT_ID
