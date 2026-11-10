"""IDM login (app 3.2.0) — offline tests, HTTP mocked via httpx.MockTransport.

Mitsubishi switched off the OAuth password grant on 2026-11-10; these tests make
sure login/refresh only use /api/v1/init, /api/v1/login and /api/v1/refreshToken.

Run: python -m pytest -p no:homeassistant tests/test_idm_login.py
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from custom_components.mitsubishi_outlander_phev_eu import api
from custom_components.mitsubishi_outlander_phev_eu.const import EU_CLIENT_ID, EU_CLIENT_SECRET

pytestmark = pytest.mark.asyncio

_RSA = RSA.generate(1024)
PUB_B64 = base64.b64encode(_RSA.publickey().export_key(format="DER")).decode()


def _decrypt_pw(value: str) -> tuple[str, str]:
    idx, b64 = value.split("@", 1)
    plain = PKCS1_v1_5.new(_RSA).decrypt(base64.b64decode(b64), None)
    return idx, plain.decode()


def _fake_idm(login_answer=None, refresh_answer=None, init_answer=None):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(api._idm_decrypt(json.loads(request.content)["payload"]))
        calls.append({"path": request.url.path, "body": body, "headers": dict(request.headers)})
        answer = {
            "/api/v1/init": init_answer or {"code": "200", "data": {"keyIndex": "K1", "publicKey": PUB_B64}},
            "/api/v1/login": login_answer,
            "/api/v1/refreshToken": refresh_answer,
        }.get(request.url.path, {"code": "404"})
        return httpx.Response(200, json={"payload": api._idm_encrypt(json.dumps(answer))})

    return calls, httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client(http: httpx.AsyncClient, username="u@x.de", password="pw-1") -> api.MitsubishiEUClient:
    c = api.MitsubishiEUClient(username, password, "1234")
    c._http = http
    c.kintaro_calls = 0

    async def fake_kintaro_init() -> bool:
        c.kintaro_calls += 1
        return True

    c._kintaro_init = fake_kintaro_init
    return c


async def test_payload_roundtrip():
    s = json.dumps({"a": 1, "ü": "ß"})
    assert api._idm_decrypt(api._idm_encrypt(s)) == s


async def test_headers_signature():
    h = api._idm_headers("dev1", ts="1700000000000", nonce="n-1")
    assert h["X-Signature"] == api._md5h(EU_CLIENT_ID + "n-1" + "1700000000000")
    assert h["X-Encrypt-Payload"] == "true"
    assert h["X-Device-Id"] == "dev1"
    assert h["X-Client-Id"] == EU_CLIENT_ID


async def test_password_rsa_keyindex():
    assert _decrypt_pw(api._idm_encrypt_password("geheim!1", PUB_B64, "k9")) == ("k9", "geheim!1")


async def test_device_id_stable_per_user():
    assert api._idm_device_id("a@b.de") == api._idm_device_id("a@b.de")
    assert api._idm_device_id("a@b.de") != api._idm_device_id("c@b.de")
    assert len(api._idm_device_id("a@b.de")) == 16


async def test_login_init_then_login_tokens_taken():
    calls, http = _fake_idm(login_answer={"code": "200", "data": {"accessToken": "AT", "refreshToken": "RT", "expiresIn": 7200}})
    c = _client(http)
    assert await c.async_login() is True
    assert [x["path"] for x in calls] == ["/api/v1/init", "/api/v1/login"]
    lb = calls[1]["body"]
    assert lb["username"] == "u@x.de"
    assert lb["clientId"] == EU_CLIENT_ID
    assert _decrypt_pw(lb["password"]) == ("K1", "pw-1")
    assert lb["deviceId"] == calls[0]["body"]["deviceId"]
    assert not any("oauth" in x["path"] for x in calls)
    assert c._token.access_token == "AT"
    assert c._token.refresh_token == "RT"
    assert c._token.is_valid
    assert c.kintaro_calls == 1


async def test_login_rejected_no_retry_no_kintaro():
    calls, http = _fake_idm(login_answer={"code": "401", "message": "wrong"})
    c = _client(http)
    assert await c.async_login() is False
    assert [x["path"] for x in calls] == ["/api/v1/init", "/api/v1/login"]  # exactly one login attempt
    assert c.kintaro_calls == 0
    assert c._token.access_token == ""


async def test_login_init_failure_stops_before_login():
    calls, http = _fake_idm(init_answer={"code": "500"})
    c = _client(http)
    assert await c.async_login() is False
    assert [x["path"] for x in calls] == ["/api/v1/init"]


async def test_refresh_uses_refresh_endpoint_keeps_old_rt():
    calls, http = _fake_idm(refresh_answer={"code": "200", "data": {"accessToken": "AT2", "expiresIn": 7200}})
    c = _client(http)
    c._token = api.TokenState(access_token="AT", refresh_token="RT")
    assert await c.async_refresh_token() is True
    assert [x["path"] for x in calls] == ["/api/v1/refreshToken"]
    assert calls[0]["body"] == {"clientId": EU_CLIENT_ID, "clientSecret": EU_CLIENT_SECRET, "refreshToken": "RT"}
    assert c._token.access_token == "AT2"
    assert c._token.refresh_token == "RT"


async def test_refresh_rejected_falls_back_to_login():
    calls, http = _fake_idm(
        refresh_answer={"code": "401"},
        login_answer={"code": "200", "data": {"accessToken": "AT3", "refreshToken": "RT3", "expiresIn": 7200}},
    )
    c = _client(http)
    c._token = api.TokenState(access_token="AT", refresh_token="RT")
    assert await c.async_refresh_token() is True
    assert [x["path"] for x in calls] == ["/api/v1/refreshToken", "/api/v1/init", "/api/v1/login"]
    assert c._token.access_token == "AT3"
