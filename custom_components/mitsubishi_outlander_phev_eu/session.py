"""Sitzungsueberwachung: Sitzungsverlust erkennen, hoechstens alle 10 min neu anmelden.

Mitsubishi erlaubt nur EINE Sitzung pro Konto. Oeffnet jemand die offizielle App,
beendet der Server die Sitzung der Integration. Die Integration meldet sich dann
einmal automatisch neu an und wartet danach mindestens BACKOFF, bevor sie das
noch einmal tut (jeder Neu-Login wirft die App wieder raus; das IDM sperrt das
Konto ausserdem nach 5 Fehl-Logins in 5 min). Der Zustand lebt hier, damit der
Diagnose-Sensor ihn auch zeigen kann, wenn der Coordinator UpdateFailed meldet.

Nichts hier loggt oder speichert Zugangsdaten, Token, VIN oder PIN.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

# Mindestabstand zwischen zwei automatischen Neu-Logins
BACKOFF = timedelta(minutes=10)

# Zustaende des Diagnose-Sensors "connection" (Enum, siehe strings.json)
STATE_OK = "ok"
STATE_SESSION_LOST = "session_lost"
STATE_WAITING_RELOGIN = "waiting_for_relogin"
STATE_VEHICLE_NOT_RESPONDING = "vehicle_not_responding"
STATE_LOGIN_FAILED = "login_failed"
STATE_NETWORK_ERROR = "network_error"

STATES = [
    STATE_OK,
    STATE_SESSION_LOST,
    STATE_WAITING_RELOGIN,
    STATE_VEHICLE_NOT_RESPONDING,
    STATE_LOGIN_FAILED,
    STATE_NETWORK_ERROR,
]


def _utcnow() -> datetime:
    """Eigene Uhr, damit Tests die Zeit setzen koennen."""
    return datetime.now(timezone.utc)


class SessionMonitor:
    """Zustand + Backoff der Sitzung eines Kontos (eine Instanz je Config-Entry)."""

    def __init__(self) -> None:
        self.state: str = STATE_OK
        self.reason: str = ""
        self.last_relogin: datetime | None = None
        self.next_relogin: datetime | None = None
        self.relogin_count: int = 0
        # Hat der Server seit dem letzten Login mindestens eine gueltige Antwort
        # geliefert? Nur dann deuten leere Antworten auf Sitzungsverlust.
        self.had_valid_response: bool = False
        # Der letzte Neu-Login brachte die Sitzung nicht zurueck: beim naechsten
        # Mal gleich voller Login statt Refresh-Token.
        self.force_full_login: bool = False
        self._listeners: list[Callable[[], None]] = []

    # -- Backoff -------------------------------------------------------
    def can_relogin(self) -> bool:
        """True, wenn ein automatischer Neu-Login jetzt erlaubt ist."""
        return self.next_relogin is None or _utcnow() >= self.next_relogin

    def start_relogin(self, reason: str) -> None:
        """Ein automatischer Neu-Login beginnt: Backoff sofort setzen (auch wenn er
        scheitert), Zaehler hoch."""
        now = _utcnow()
        self.last_relogin = now
        self.next_relogin = now + BACKOFF
        self.relogin_count += 1
        self.set_state(STATE_SESSION_LOST, reason)

    def block_logins(self, reason: str) -> None:
        """Ein Login (kein Sitzungsverlust) ist gescheitert: keine weiteren
        automatischen Logins bis zum Ablauf des Backoffs."""
        self.next_relogin = _utcnow() + BACKOFF
        self.set_state(STATE_LOGIN_FAILED, reason)

    @staticmethod
    def hhmm(value: datetime | None) -> str:
        """HH:MM in Ortszeit fuer die Log-Zeile."""
        return value.astimezone().strftime("%H:%M") if value else "?"

    # -- Zustand -------------------------------------------------------
    def set_state(self, state: str, reason: str = "") -> None:
        self.state = state
        self.reason = reason
        for cb in list(self._listeners):
            cb()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove
