"""Mitsubishi Connect EU Integration for Home Assistant."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ForceLogoutError, SessionLostError
from .session import (
    STATE_NETWORK_ERROR,
    STATE_OK,
    STATE_SESSION_LOST,
    STATE_VEHICLE_NOT_RESPONDING,
    SessionMonitor,
)
from .client import create_client
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_UPDATE_INTERVAL,
    CONF_WAKE_ON_POLL,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WAKE_ON_POLL,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


def _has_data(state) -> bool:
    return state is not None and (state.battery_level is not None or state.odometer is not None)


def _mark_ok(client) -> None:
    mon = getattr(client, "session", None)
    if mon is not None:
        mon.set_state(STATE_OK)


def _no_data_error(client, vin) -> UpdateFailed:
    """Keine Fahrzeugdaten nach 90 s: Grund trennen und im Diagnose-Sensor zeigen.

    Netzwerkfehler / Fahrzeug antwortet nicht (Server liefert gueltige Antworten,
    Sitzung ok) / Server liefert gar nichts Gueltiges, aber die Sitzung hat seit
    dem Login noch nie Daten geliefert (kein Neu-Login, der waere sinnlos)."""
    mon = getattr(client, "session", None)
    if mon is not None and mon.state == STATE_NETWORK_ERROR:
        return UpdateFailed(f"Keine Daten von der API erhalten fuer {vin} nach 90s — Netzwerkfehler")
    if getattr(client, "last_status_valid", 1):
        if mon is not None:
            mon.set_state(STATE_VEHICLE_NOT_RESPONDING, "Fahrzeug antwortet nicht")
        _LOGGER.warning("Fahrzeug antwortet nicht (Sitzung ok): keine Fahrzeugdaten nach 90 s")
        return UpdateFailed(f"Fahrzeug antwortet nicht (Sitzung ok): keine Daten fuer {vin} nach 90s")
    if mon is not None:
        mon.set_state(STATE_SESSION_LOST, "keine gültige Antwort")
    _LOGGER.warning(
        "Keine gültige Antwort vom Server nach 90 s; Sitzung unklar, "
        "kein Neu-Login (Sitzung lieferte seit dem Login noch nie Daten)"
    )
    return UpdateFailed(f"Keine gueltige Antwort vom Server fuer {vin} nach 90s (Sitzung unklar)")


async def _read_with_wake(client, vin):
    """refreshVSR ausloesen (Auto aufwecken) und pollen, bis frische Daten da sind."""
    try:
        refreshed = await client.async_refresh_status(vin)
        if not refreshed:
            _LOGGER.warning("VSR-Refresh fehlgeschlagen fuer %s, lese trotzdem Status", vin)

        # Auto braucht Zeit zum Aufwachen (Mobilfunk-Modem, Verbindung).
        # Erste Abfrage nach 15s, dann alle 10s nochmal, max 90s warten.
        state = None
        for attempt in range(1, 8):
            wait = 15 if attempt == 1 else 10
            await asyncio.sleep(wait)
            state = await client.async_get_vehicle_status(vin)
            if _has_data(state):
                _LOGGER.debug(
                    "Frische Daten fuer %s nach %s Sekunden (Versuch %s)",
                    vin, 15 + (attempt - 1) * 10, attempt,
                )
                _mark_ok(client)
                return state

        # Nach 90s immer noch keine Daten
        if state is not None and not _has_data(state):
            raise _no_data_error(client, vin)
        return state
    except (UpdateFailed, SessionLostError):
        raise
    except Exception as err:
        raise UpdateFailed(f"Fehler beim Aktualisieren von {vin}: {err}") from err


async def _read_without_wake(client, coordinator, vin):
    """Status lesen ohne refreshVSR und ohne Wartezeit (Option "Auto aufwecken" aus).

    Die Daten sind so alt wie die letzte Meldung des Autos. Kommt nichts zurueck,
    bleiben vorhandene Daten stehen. Hat die Integration noch GAR keine Daten
    (erster Abruf nach Start/Reload) und der Server liefert ohne Aufwecken nichts,
    wird genau einmal geweckt; bringt auch das nichts, startet der Eintrag trotzdem
    (Werte unbekannt, Button "Status aktualisieren" bleibt nutzbar). Bis b4 lief
    hier UpdateFailed -> ConfigEntryNotReady -> Setup-Retry ohne Ende."""
    try:
        state = await client.async_get_vehicle_status(vin)
    except SessionLostError:
        raise
    except Exception as err:
        raise UpdateFailed(f"Fehler beim Aktualisieren von {vin}: {err}") from err
    if _has_data(state):
        _mark_ok(client)
        return state
    previous = getattr(coordinator, "data", None)
    if previous is not None:
        _LOGGER.debug("Keine neuen Daten fuer %s (Aufwecken aus), behalte alte Daten", vin)
        return previous
    _LOGGER.info(
        "Noch keine Daten fuer %s und Aufwecken ist aus: wecke das Auto einmalig beim Start", vin
    )
    try:
        return await _read_with_wake(client, vin)
    except UpdateFailed as err:
        if state is None:
            raise
        _LOGGER.warning(
            "Keine Daten fuer %s (%s). Eintrag startet trotzdem, Werte bleiben unbekannt, "
            "bis das Auto sich meldet oder der Button \"Status aktualisieren\" gedrueckt wird.",
            vin, err,
        )
        return state


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mitsubishi Connect EU from a config entry."""
    client = create_client(entry.data, use_ha_ssl=True)
    # Der Monitor ueberlebt ein Neuladen des Eintrags (Optionen speichern): so bleibt
    # der 10-min-Backoff fuer automatische Neu-Logins erhalten.
    if hasattr(client, "session"):
        client.session = hass.data.setdefault(f"{DOMAIN}_sessions", {}).setdefault(
            entry.entry_id, client.session
        )
    wake_on_poll = entry.options.get(CONF_WAKE_ON_POLL, DEFAULT_WAKE_ON_POLL)

    if not await client.async_login():
        raise ConfigEntryAuthFailed("Invalid credentials for Mitsubishi Connect EU")

    try:
        vehicles = await client.async_get_vehicles()
    except ForceLogoutError as err:
        await client.async_close()
        raise ConfigEntryNotReady(str(err)) from err
    if not vehicles:
        raise ConfigEntryNotReady("No vehicles found on account")

    # VIN-Deduplizierung: nur ein Eintrag pro VIN
    seen_vins: set[str] = set()
    unique_vehicles: list[dict] = []
    for v in vehicles:
        v_vin = v.get("vin", "")
        if v_vin and v_vin not in seen_vins:
            seen_vins.add(v_vin)
            unique_vehicles.append(v)
    vehicles = unique_vehicles
    _LOGGER.debug("Fahrzeuge nach Deduplizierung: %s", [v.get("vin") for v in vehicles])

    update_interval = timedelta(
        minutes=entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
    )

    coordinators: dict[str, DataUpdateCoordinator] = {}
    for vehicle in vehicles:
        vin = vehicle.get("vin", "")
        if not vin:
            continue

        async def _update_vehicle(v=vin):
            # Sitzungsverlust: der Client meldet sich hoechstens einmal je 10 min neu
            # an (SessionMonitor); hier nur auswerten und den Grund melden.
            begin = getattr(client, "begin_cycle", None)
            if begin:
                begin()
            try:
                if not wake_on_poll:
                    return await _read_without_wake(client, coordinators.get(v), v)
                return await _read_with_wake(client, v)
            except SessionLostError as err:
                if err.auth_rejected:
                    raise ConfigEntryAuthFailed(
                        "Mitsubishi Connect EU hat die Zugangsdaten abgelehnt"
                    ) from err
                raise UpdateFailed(str(err)) from err

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{vin}",
            update_method=_update_vehicle,
            update_interval=update_interval,
        )
        coordinator.wake_on_poll = wake_on_poll
        coordinators[vin] = coordinator
        try:
            await coordinator.async_config_entry_first_refresh()
        except Exception:
            await client.async_close()
            raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinators": coordinators,
        "vehicles": vehicles,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Robust gegen doppeltes Entladen: fehlt der Eintrag in hass.data schon,
    gibt es keinen KeyError (b3 Z.122, b4 Z.148)."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data is not None:
            await data["client"].async_close()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update-Listener: Neu laden ueber den HA-Lebenszyklus.

    Bis b4 rief der Listener async_unload_entry/async_setup_entry direkt auf, an
    HA vorbei: der Eintrag blieb fuer HA "geladen", der Coordinator hatte keinen
    Config-Entry (ConfigEntryError im ersten Refresh), hass.data war schon leer
    und das naechste echte Entladen endete im KeyError."""
    hass.config_entries.async_schedule_reload(entry.entry_id)
