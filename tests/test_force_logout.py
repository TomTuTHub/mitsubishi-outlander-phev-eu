"""Offline tests v1.0.10: errorCode 600002 (ForceLogout).

Der Server beendet die Sitzung (typisch: dasselbe Konto ist woanders angemeldet).
Erwartet: genau EIN neuer Login pro Zyklus und die Abfrage einmal wiederholen.
Kommt 600002 danach wieder: ForceLogoutError sofort (keine Schleife, kein
90-s-Polling).

Keine Netzwerkzugriffe: httpx laeuft ueber MockTransport, Krypto-Helfer ersetzt.
"""
import asyncio
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "mitsubishi_outlander_phev_eu"
if "mitsubishi_outlander_phev_eu" not in sys.modules:
    _stub = types.ModuleType("mitsubishi_outlander_phev_eu")
    _stub.__path__ = [str(_PKG)]
    sys.modules["mitsubishi_outlander_phev_eu"] = _stub

from mitsubishi_outlander_phev_eu import api  # noqa: E402
from mitsubishi_outlander_phev_eu import const  # noqa: E402

FORCED = {"state": "F", "errorCode": "600002"}
OK = {"state": "S", "ok": True}
VIN = "TESTVIN0000000001"


def run(coro):
    return asyncio.run(coro)


class Harness:
    """Client mit gezaehlten Logins und einem Skript an Server-Antworten."""

    def __init__(self, monkeypatch, answers, login_ok=True):
        monkeypatch.setattr(api, "_encrypt_body", lambda body, key: "ENC")
        monkeypatch.setattr(api, "_compute_sign", lambda *a, **k: "SIGN")
        self.client = api.MitsubishiEUClient("u@example.org", "pw", "1234")
        self.logins = 0
        self.requests: list[tuple[str, str]] = []
        self._answers = answers
        self._login_ok = login_ok
        self._valid()
        self.client._pin_verified = True
        self.client._pin_hash = "PINHASH"
        self.client.async_login = self._login
        self.client._http = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _valid(self):
        self.client._token = api.TokenState(
            access_token="AT", refresh_token="RT",
            expires_at=datetime.now() + timedelta(hours=1))
        self.client._enc_key = "K"
        self.client._sign_key = "S"

    async def _login(self):
        self.logins += 1
        if self._login_ok:
            self._valid()
        return self._login_ok

    def _handle(self, request):
        path = request.url.path
        endpoint = next((e for e in (const.EP_VSR, const.EP_CHARGE_DETAILS, const.EP_REFRESH_VSR,
                                     const.EP_VEHICLE_LIST, const.EP_START_HORN,
                                     const.EP_GENERATE_NONCE)
                         if path.endswith(e)), path)
        self.requests.append((request.method, endpoint))
        return httpx.Response(200, content=json.dumps(self._answers(request.method, endpoint)))


def test_get_force_logout_once_relogin_and_retry(monkeypatch):
    seq = iter([FORCED, OK])
    h = Harness(monkeypatch, lambda m, e: next(seq))
    assert run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN})) == OK
    assert h.logins == 1
    assert h.requests == [("GET", const.EP_VSR)] * 2


def test_get_force_logout_twice_raises_no_loop(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN}))
    assert h.logins == 1
    assert len(h.requests) == 2


def test_post_force_logout_once_relogin_and_retry(monkeypatch):
    seq = iter([FORCED, OK])
    h = Harness(monkeypatch, lambda m, e: next(seq))
    assert run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN})) == OK
    assert h.logins == 1
    assert h.client.last_error_code is None


def test_post_force_logout_twice_raises(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN}))
    assert h.logins == 1
    assert len(h.requests) == 2


def test_relogin_failure_raises_without_second_login(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED, login_ok=False)
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN}))
    assert h.logins == 1
    assert len(h.requests) == 1


def test_only_one_relogin_per_cycle_across_endpoints(monkeypatch):
    seq = iter([FORCED, OK, FORCED])
    h = Harness(monkeypatch, lambda m, e: next(seq))
    run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN}))
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_get(const.EP_CHARGE_DETAILS, {"vin": VIN}))
    assert h.logins == 1


def test_begin_cycle_allows_one_relogin_again(monkeypatch):
    seq = iter([FORCED, OK, FORCED, OK])
    h = Harness(monkeypatch, lambda m, e: next(seq))
    run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN}))
    h.client.begin_cycle()
    assert run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN})) == OK
    assert h.logins == 2


def test_vehicle_status_aborts_fast_on_persistent_force_logout(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client.async_get_vehicle_status(VIN))
    assert h.logins == 1
    assert len(h.requests) == 2


def test_refresh_status_raises_on_persistent_force_logout(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client.async_refresh_status(VIN))
    assert h.logins == 1


def test_pin_verify_does_not_swallow_force_logout(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    h.client._pin_verified = False
    with pytest.raises(api.ForceLogoutError):
        run(h.client._ensure_pin(VIN))
    assert h.logins == 1


def test_command_with_persistent_force_logout_returns_false_with_code(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    h.client._force_relogin_used = True
    assert run(h.client.async_horn(VIN)) is False
    assert h.logins == 1
    assert h.client.last_error_code == "600002"


def test_other_error_codes_never_relogin(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: {"state": "F", "errorCode": "600001"})
    assert run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN})) is None
    assert run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN})) is None
    assert h.logins == 0
    assert len(h.requests) == 2


def test_force_logout_numeric_error_code_is_detected(monkeypatch):
    seq = iter([{"state": "F", "errorCode": 600002}, OK])
    h = Harness(monkeypatch, lambda m, e: next(seq))
    assert run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN})) == OK
    assert h.logins == 1
