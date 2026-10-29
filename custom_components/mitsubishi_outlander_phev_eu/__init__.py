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
                return state

        # Nach 90s immer noch keine Daten
        if state is not None and not _has_data(state):
            raise UpdateFailed(
                f"Keine Daten von der API erhalten fuer {vin} nach 90s — "
                "Fahrzeug antwortet nicht oder Session abgelaufen"
            )
        return state
    except UpdateFailed:
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
    except Exception as err:
        raise UpdateFailed(f"Fehler beim Aktualisieren von {vin}: {err}") from err
    if _has_data(state):
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
    wake_on_poll = entry.options.get(CONF_WAKE_ON_POLL, DEFAULT_WAKE_ON_POLL)

    if not await client.async_login():
        raise ConfigEntryAuthFailed("Invalid credentials for Mitsubishi Connect EU")

    vehicles = await client.async_get_vehicles()
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
            if not wake_on_poll:
                return await _read_without_wake(client, coordinators.get(v), v)
            return await _read_with_wake(client, v)

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
