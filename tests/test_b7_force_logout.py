"""Offline tests v1.1.0b7: errorCode 600002 (ForceLogout).

Der Server beendet die Sitzung (typisch: dasselbe Konto ist woanders angemeldet).
Erwartet: genau EIN neuer Login pro Zyklus und die Abfrage einmal wiederholen.
Kommt 600002 danach wieder: ForceLogoutError sofort (keine Schleife, kein
90-s-Polling). Gleiches Verhalten fuer EU und JP.

Keine Netzwerkzugriffe: _send und die Krypto-Helfer sind ersetzt.
"""
import asyncio
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
    """Client mit gezaehlten Logins und einem Skript an Server-Antworten.

    `answers(method, endpoint)` liefert die JSON-Antwort fuer den naechsten Request."""

    def __init__(self, monkeypatch, region, answers, login_ok=True):
        monkeypatch.setattr(api, "_encrypt_body", lambda body, key, p=None: "ENC")
        monkeypatch.setattr(api, "_compute_sign", lambda *a, **k: "SIGN")
        self.client = api.MitsubishiEUClient("u@example.org", "pw", "1234", region=region)
        self.logins = 0
        self.requests: list[tuple[str, str]] = []
        self._answers = answers
        self._login_ok = login_ok
        self._valid()
        self.client._pin_verified = True
        self.client._pin_hash = "PINHASH"
        self.client.async_login = self._login
        self.client._send = self._send

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

    async def _send(self, method, name, url, **kw):
        self.requests.append((method, name))
        return httpx.Response(200, json=self._answers(method, name))


REGIONS = ["eu", "jp_1"]


@pytest.mark.parametrize("region", REGIONS)
def test_get_force_logout_once_relogin_and_retry(monkeypatch, region):
    seq = iter([FORCED, OK])
    h = Harness(monkeypatch, region, lambda m, e: next(seq))
    data, failed = run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    assert data == OK and failed is False
    assert h.logins == 1
    assert h.requests == [("GET", const.EP_VSR)] * 2


@pytest.mark.parametrize("region", REGIONS)
def test_get_force_logout_twice_raises_no_loop(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    assert h.logins == 1
    assert len(h.requests) == 2


@pytest.mark.parametrize("region", REGIONS)
def test_post_force_logout_once_relogin_and_retry(monkeypatch, region):
    seq = iter([FORCED, OK])
    h = Harness(monkeypatch, region, lambda m, e: next(seq))
    assert run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN})) == OK
    assert h.logins == 1
    assert h.client.last_error_code is None


@pytest.mark.parametrize("region", REGIONS)
def test_post_force_logout_twice_raises(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN}))
    assert h.logins == 1
    assert len(h.requests) == 2


@pytest.mark.parametrize("region", REGIONS)
def test_relogin_failure_raises_without_second_login(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: FORCED, login_ok=False)
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    assert h.logins == 1
    assert len(h.requests) == 1


@pytest.mark.parametrize("region", REGIONS)
def test_only_one_relogin_per_cycle_across_endpoints(monkeypatch, region):
    """Erst VSR 600002 -> Login -> ok; dann Ladestatus 600002: kein zweiter Login
    im selben Zyklus, sondern ForceLogoutError (Ping-Pong mit zweiter Sitzung)."""
    seq = iter([FORCED, OK, FORCED])
    h = Harness(monkeypatch, region, lambda m, e: next(seq))
    run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    with pytest.raises(api.ForceLogoutError):
        run(h.client._kintaro_get_ex(const.EP_CHARGE_DETAILS, {"vin": VIN}))
    assert h.logins == 1


@pytest.mark.parametrize("region", REGIONS)
def test_begin_cycle_allows_one_relogin_again(monkeypatch, region):
    seq = iter([FORCED, OK, FORCED, OK])
    h = Harness(monkeypatch, region, lambda m, e: next(seq))
    run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    h.client.begin_cycle()
    data, _ = run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    assert data == OK
    assert h.logins == 2


@pytest.mark.parametrize("region", REGIONS)
def test_vehicle_status_aborts_fast_on_persistent_force_logout(monkeypatch, region):
    """Statusabfrage mit dauerhaftem 600002: 1 Login, 2 Requests, dann Abbruch
    (bis b6: alle Endpoints leer, Coordinator wartete 90 s auf Daten)."""
    h = Harness(monkeypatch, region, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client.async_get_vehicle_status(VIN))
    assert h.logins == 1
    assert len(h.requests) == 2


@pytest.mark.parametrize("region", REGIONS)
def test_refresh_status_raises_on_persistent_force_logout(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h.client.async_refresh_status(VIN))
    assert h.logins == 1


@pytest.mark.parametrize("region", REGIONS)
def test_pin_verify_does_not_swallow_force_logout(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: FORCED)
    h.client._pin_verified = False
    with pytest.raises(api.ForceLogoutError):
        run(h.client._ensure_pin(VIN))
    assert h.logins == 1


@pytest.mark.parametrize("region", REGIONS)
def test_command_with_persistent_force_logout_returns_false_with_code(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: FORCED)
    h.client._force_relogin_used = True          # Zyklus vorher schon verbraucht
    assert run(h.client.async_horn(VIN)) is False   # Befehl = eigener Zyklus
    assert h.logins == 1
    assert h.client.last_error_code == "600002"


@pytest.mark.parametrize("region", REGIONS)
def test_other_error_codes_never_relogin(monkeypatch, region):
    h = Harness(monkeypatch, region, lambda m, e: {"state": "F", "errorCode": "600001"})
    data, failed = run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    assert data is None and failed is False
    assert run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN})) is None
    assert h.logins == 0
    assert len(h.requests) == 2


def test_force_logout_numeric_error_code_is_detected(monkeypatch):
    seq = iter([{"state": "F", "errorCode": 600002}, OK])
    h = Harness(monkeypatch, "eu", lambda m, e: next(seq))
    data, _ = run(h.client._kintaro_get_ex(const.EP_VSR, {"vin": VIN}))
    assert data == OK and h.logins == 1
