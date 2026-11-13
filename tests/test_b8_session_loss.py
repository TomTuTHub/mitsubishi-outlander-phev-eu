"""Offline tests v1.1.0b8: Sitzungsverlust sauber behandeln (EU und JP).

Mitsubishi erlaubt nur eine Sitzung pro Konto. Oeffnet jemand die App, ist die
Sitzung der Integration tot. Erwartet:
  * Erkennung: errorCode 600002, HTTP 401/403, Token ungueltig, leere Antworten
    (nur wenn die Sitzung vorher gueltige Antworten lieferte)
  * genau EIN automatischer Neu-Login (Refresh-Token zuerst), danach >= 10 min
    Backoff, nie in Schleife, auch nicht nach fehlgeschlagenem Login
  * "Fahrzeug antwortet nicht" (gueltige Antworten, keine Fahrzeugdaten) und
    Netzfehler loesen KEINEN Neu-Login aus
  * Log ohne Zugangsdaten / VIN / PIN

Keine Netzwerkzugriffe: httpx laeuft ueber MockTransport, Krypto-Helfer ersetzt,
die Uhr des SessionMonitor ist gesetzt. Region-Profil und JP-Login-Weg bleiben
unberuehrt, die Sitzungslogik gilt fuer alle Regionen.
"""
import asyncio
import json
import logging
import sys
import types
from datetime import datetime, timedelta, timezone
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
from mitsubishi_outlander_phev_eu import session as sess  # noqa: E402

FORCED = {"state": "F", "errorCode": "600002"}
OK = {"state": "S", "ok": True}
OTHER = {"state": "F", "errorCode": "999999"}
VIN = "TESTVIN0000000001"
PASSWORD = "geheimes-passwort-xyz"
PIN = "4711"


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class Harness:
    """Client mit gezaehlten Logins/Refreshes und einem Skript an Server-Antworten.

    answers(method, endpoint) -> dict | (http_status, text) | Exception."""

    def __init__(self, monkeypatch, answers, login_ok=True, refresh_ok=True, reject=False, region="eu"):
        monkeypatch.setattr(api, "_encrypt_body", lambda body, key, p=None: "ENC")
        monkeypatch.setattr(api, "_compute_sign", lambda *a, **k: "SIGN")
        self.clock = Clock()
        monkeypatch.setattr(sess, "_utcnow", self.clock)
        self.client = api.MitsubishiEUClient("u@example.org", PASSWORD, PIN, region=region)
        self.mon = self.client.session
        self.logins = 0
        self.refreshes = 0
        self.requests: list[tuple[str, str]] = []
        self.answers = answers
        self.login_ok = login_ok
        self.refresh_ok = refresh_ok
        self.reject = reject
        self._valid()
        self.client._pin_verified = True
        self.client._pin_hash = "PINHASH"
        self.client.async_login = self._login
        self.client.async_refresh_token = self._refresh
        self.client._send = self._send

    def _valid(self):
        self.client._token = api.TokenState(
            access_token="AT", refresh_token="RT",
            expires_at=datetime.now() + timedelta(hours=1))
        self.client._enc_key = "K"
        self.client._sign_key = "S"
        self.mon.had_valid_response = False

    async def _login(self):
        self.logins += 1
        if self.login_ok:
            self._valid()
            return True
        self.client.login_rejected = self.reject
        return False

    async def _refresh(self):
        self.refreshes += 1
        if self.refresh_ok:
            self._valid()
            return True
        return await self._login()

    @property
    def auto_logins(self):
        """Neu-Logins gesamt (Refresh-Versuche zaehlen, ein Fallback-Login darin nicht doppelt)."""
        return self.refreshes + (self.logins if not self.refreshes else 0)

    async def _send(self, method, name, url, **kw):
        self.requests.append((method, name))
        a = self.answers(method, name)
        if isinstance(a, Exception):
            raise a
        if isinstance(a, tuple):
            return httpx.Response(a[0], content=a[1])
        return httpx.Response(200, json=a)


def get(h):
    return run(h.client._kintaro_get(const.EP_VSR, {"vin": VIN}))


def seq_answers(*items):
    it = iter(items)
    return lambda m, e: next(it)


# ---------------------------------------------------------------------------
# 1. Erkennung
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,body,expected", [
    (200, FORCED, "errorCode 600002"),
    (200, {"state": "F", "errorCode": 600002}, "errorCode 600002"),
    (401, None, "HTTP 401"),
    (403, None, "HTTP 403"),
    (200, {"state": "F", "errorCode": "401001", "message": "Invalid token"}, "Token/Sitzung ungueltig (errorCode 401001)"),
    (200, {"state": "F", "errorCode": "x", "errorMessage": "Unauthorized"}, "Token/Sitzung ungueltig (errorCode x)"),
])
def test_session_loss_detected(status, body, expected):
    assert api._session_lost_reason(status, body) == expected


@pytest.mark.parametrize("status,body", [
    (200, OK),
    (200, OTHER),
    (200, {"state": "F", "errorCode": "600001"}),
    (500, {"state": "F", "errorCode": "1"}),
    (200, None),
])
def test_no_session_loss_for_other_answers(status, body):
    assert api._session_lost_reason(status, body) is None


@pytest.mark.parametrize("first", [FORCED, (401, "unauthorized"), (403, "{}"),
                                   {"state": "F", "errorCode": "1", "message": "token expired"}])
@pytest.mark.parametrize("region", ["eu", "jp_1"])
def test_get_loss_relogins_once_refresh_first_and_retries(monkeypatch, first, region):
    h = Harness(monkeypatch, seq_answers(first, OK), region=region)
    assert get(h) == OK
    assert h.refreshes == 1 and h.logins == 0       # Refresh-Token zuerst
    assert h.requests == [("GET", const.EP_VSR)] * 2
    assert h.mon.relogin_count == 1
    assert h.mon.state == sess.STATE_OK              # gueltige Antwort nach Neu-Login
    assert h.mon.next_relogin == h.clock.now + sess.BACKOFF
    assert h.mon.last_relogin == h.clock.now


def test_post_loss_relogins_once_and_retries(monkeypatch):
    h = Harness(monkeypatch, seq_answers(FORCED, OK))
    assert run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN})) == OK
    assert h.auto_logins == 1
    assert h.client.last_error_code is None


def test_refresh_rejected_falls_back_to_full_login(monkeypatch):
    h = Harness(monkeypatch, seq_answers(FORCED, OK), refresh_ok=False)
    assert get(h) == OK
    assert h.refreshes == 1 and h.logins == 1        # ein Fallback, kein Extra-Login


# ---------------------------------------------------------------------------
# 2. Backoff, keine Schleife
# ---------------------------------------------------------------------------

def test_second_loss_within_backoff_does_not_login(monkeypatch):
    h = Harness(monkeypatch, seq_answers(FORCED, OK, FORCED))
    get(h)
    h.clock.advance(minutes=9, seconds=59)
    h.client.begin_cycle()
    with pytest.raises(api.SessionLostError) as ei:
        get(h)
    assert not ei.value.auth_rejected
    assert h.auto_logins == 1
    assert h.mon.state == sess.STATE_WAITING_RELOGIN
    assert len(h.requests) == 3                      # keine Wiederholung ohne Login


def test_after_backoff_a_new_login_is_allowed(monkeypatch):
    h = Harness(monkeypatch, seq_answers(FORCED, OK, FORCED, OK))
    get(h)
    h.clock.advance(minutes=10, seconds=1)
    h.client.begin_cycle()
    assert get(h) == OK
    assert h.refreshes == 2
    assert h.mon.relogin_count == 2


@pytest.mark.parametrize("region", ["eu", "jp_1"])
def test_never_loops_over_many_cycles(monkeypatch, region):
    h = Harness(monkeypatch, lambda m, e: FORCED, region=region)
    for _ in range(30):
        h.client.begin_cycle()
        h.clock.advance(seconds=20)                   # 30 Zyklen = 10 min
        with pytest.raises(api.SessionLostError):
            get(h)
    assert h.auto_logins == 1
    assert h.mon.state == sess.STATE_WAITING_RELOGIN


def test_dead_after_relogin_marks_full_login_next_time(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.SessionLostError):
        get(h)
    assert h.refreshes == 1 and h.logins == 0
    assert h.mon.force_full_login is True
    h.clock.advance(minutes=11)
    h.client.begin_cycle()
    with pytest.raises(api.SessionLostError):
        get(h)
    assert h.refreshes == 1 and h.logins == 1        # diesmal gleich voller Login


def test_login_failure_blocks_further_logins_until_backoff(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED, login_ok=False, refresh_ok=False)
    with pytest.raises(api.SessionLostError):
        get(h)
    assert h.logins == 1 and h.mon.state == sess.STATE_LOGIN_FAILED
    for _ in range(5):
        h.client.begin_cycle()
        h.clock.advance(minutes=1)
        with pytest.raises((api.SessionLostError, ConnectionError)):
            get(h)
    assert h.logins == 1                              # 5 min spaeter: immer noch keiner
    h.clock.advance(minutes=6)
    with pytest.raises((api.SessionLostError, ConnectionError)):
        get(h)
    assert h.logins == 2                              # erst nach Ablauf wieder EIN Versuch (kein Doppel-Login)


@pytest.mark.parametrize("reject", [True, False])
def test_auth_rejected_flag_is_passed_on(monkeypatch, reject):
    h = Harness(monkeypatch, lambda m, e: FORCED, login_ok=False, refresh_ok=False, reject=reject)
    with pytest.raises(api.SessionLostError) as ei:
        get(h)
    assert ei.value.auth_rejected is reject


def test_expired_token_login_failure_blocks_autologin(monkeypatch):
    """Kein Sitzungsverlust, sondern abgelaufenes Token + Login scheitert."""
    h = Harness(monkeypatch, lambda m, e: OK, login_ok=False, refresh_ok=False)
    h.client._token = api.TokenState()               # abgelaufen, ohne Refresh-Token
    with pytest.raises(ConnectionError):
        get(h)
    assert h.logins == 1 and h.mon.state == sess.STATE_LOGIN_FAILED
    for _ in range(4):
        h.clock.advance(minutes=2)
        with pytest.raises(ConnectionError):
            get(h)
    assert h.logins == 1
    h.clock.advance(minutes=3)
    with pytest.raises(ConnectionError):
        get(h)
    assert h.logins == 2


# ---------------------------------------------------------------------------
# 3. Leere Antworten / Fahrzeug antwortet nicht / Netz
# ---------------------------------------------------------------------------

def _warm_up(h):
    h.mon.had_valid_response = True


@pytest.mark.parametrize("region", ["eu", "jp_1"])
def test_empty_answers_after_valid_session_trigger_one_relogin(monkeypatch, region):
    state = {"dead": True}

    def answers(m, e):
        if state["dead"] and h.refreshes == 0:
            return OTHER
        return OK
    h = Harness(monkeypatch, answers, region=region)
    _warm_up(h)
    st = run(h.client.async_get_vehicle_status(VIN))
    assert st is not None
    assert h.auto_logins == 1
    assert h.client.last_status_valid > 0
    assert h.mon.state == sess.STATE_OK


def test_empty_answers_still_dead_after_relogin_raises_and_stops(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: OTHER)
    _warm_up(h)
    with pytest.raises(api.SessionLostError):
        run(h.client.async_get_vehicle_status(VIN))
    assert h.auto_logins == 1
    assert h.mon.state == sess.STATE_WAITING_RELOGIN
    # naechster Poll innerhalb des Backoffs: kein Login
    h.client.begin_cycle()
    h.mon.had_valid_response = True
    with pytest.raises(api.SessionLostError):
        run(h.client.async_get_vehicle_status(VIN))
    assert h.auto_logins == 1


def test_empty_answers_without_prior_valid_session_do_not_login(monkeypatch):
    """Sitzung lieferte seit dem Login nie etwas Gueltiges: kein Neu-Login (waere nutzlos)."""
    h = Harness(monkeypatch, lambda m, e: OTHER)
    st = run(h.client.async_get_vehicle_status(VIN))
    assert st is not None
    assert h.auto_logins == 0
    assert h.client.last_status_valid == 0


def test_vehicle_not_responding_is_not_session_loss(monkeypatch):
    """Gueltige Antworten, aber keine Fahrzeugdaten: Sitzung ok, kein Login."""
    h = Harness(monkeypatch, lambda m, e: OK)
    _warm_up(h)
    st = run(h.client.async_get_vehicle_status(VIN))
    assert st.battery_level is None and st.odometer is None
    assert h.auto_logins == 0
    assert h.client.last_status_valid > 0
    assert h.mon.state == sess.STATE_OK


def test_network_errors_are_not_session_loss(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: httpx.ConnectError("down"))
    _warm_up(h)
    run(h.client.async_get_vehicle_status(VIN))
    assert h.auto_logins == 0
    assert h.mon.state == sess.STATE_NETWORK_ERROR


def test_other_error_codes_never_relogin(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: {"state": "F", "errorCode": "600001"})
    assert get(h) is None
    assert run(h.client._kintaro_post(const.EP_REFRESH_VSR, {"vin": VIN})) is None
    assert h.auto_logins == 0
    assert len(h.requests) == 2


def test_pin_verify_and_refresh_status_propagate_session_loss(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    h.client._pin_verified = False
    with pytest.raises(api.ForceLogoutError):
        run(h.client._ensure_pin(VIN))
    h2 = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.ForceLogoutError):
        run(h2.client.async_refresh_status(VIN))
    assert h2.auto_logins == 1


def test_command_with_session_loss_returns_false_with_code(monkeypatch):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    assert run(h.client.async_horn(VIN)) is False
    assert h.auto_logins == 1
    assert h.client.last_error_code == "600002"


# ---------------------------------------------------------------------------
# 4. Log-Zeilen, keine Geheimnisse
# ---------------------------------------------------------------------------

def test_log_lines_on_recovery(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    h = Harness(monkeypatch, seq_answers(FORCED, OK))
    get(h)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert "Sitzung verloren (errorCode 600002) – melde neu an" in warnings


def test_log_lines_in_backoff_once_per_cycle(monkeypatch, caplog):
    h = Harness(monkeypatch, seq_answers(FORCED, OK, FORCED, FORCED))
    get(h)
    caplog.set_level(logging.DEBUG)
    caplog.clear()
    h.clock.advance(minutes=1)
    h.client.begin_cycle()
    for _ in range(2):
        with pytest.raises(api.SessionLostError):
            get(h)
    expected = h.mon.hhmm(h.mon.next_relogin)
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and "nächster Neu-Login frühestens" in r.getMessage()]
    assert lines == [f"Sitzung verloren (errorCode 600002), nächster Neu-Login frühestens {expected}"]


def test_log_after_dead_relogin(monkeypatch, caplog):
    h = Harness(monkeypatch, lambda m, e: FORCED)
    with pytest.raises(api.SessionLostError):
        get(h)
    expected = h.mon.hhmm(h.mon.next_relogin)
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert f"Sitzung verloren, nächster Neu-Login frühestens {expected}" in warnings


def test_no_secrets_in_log(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    h = Harness(monkeypatch, lambda m, e: FORCED, login_ok=False, refresh_ok=False)
    for _ in range(3):
        h.client.begin_cycle()
        with pytest.raises((api.SessionLostError, ConnectionError)):
            get(h)
        run(h.client.async_horn(VIN))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (PASSWORD, PIN, VIN, "u@example.org", "PINHASH", "AT", "RT"):
        assert secret not in text, secret


# ---------------------------------------------------------------------------
# 5. Monitor / Sensor-Zustand
# ---------------------------------------------------------------------------

def test_monitor_initial_and_attributes(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(sess, "_utcnow", clock)
    m = sess.SessionMonitor()
    assert m.state == sess.STATE_OK and m.relogin_count == 0
    assert m.last_relogin is None and m.next_relogin is None and m.can_relogin()
    m.start_relogin("errorCode 600002")
    assert m.state == sess.STATE_SESSION_LOST
    assert m.relogin_count == 1 and m.last_relogin == clock.now
    assert m.next_relogin == clock.now + timedelta(minutes=10)
    assert not m.can_relogin()
    clock.advance(minutes=10)
    assert m.can_relogin()


def test_monitor_notifies_listeners_and_can_unsubscribe():
    m = sess.SessionMonitor()
    seen = []
    off = m.add_listener(lambda: seen.append(m.state))
    m.set_state(sess.STATE_WAITING_RELOGIN, "x")
    off()
    m.set_state(sess.STATE_OK)
    assert seen == [sess.STATE_WAITING_RELOGIN]


def test_states_match_translations():
    for rel in ("strings.json", "translations/de.json", "translations/en.json", "translations/ja.json"):
        d = json.loads((_PKG / rel).read_text(encoding="utf-8"))
        assert set(d["entity"]["sensor"]["connection"]["state"]) == set(sess.STATES), rel
