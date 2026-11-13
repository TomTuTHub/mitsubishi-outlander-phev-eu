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

from .api import ForceLogoutError, MitsubishiEUClient, SessionLostError, VehicleState
from .session import (
    STATE_NETWORK_ERROR,
    STATE_OK,
    STATE_SESSION_LOST,
    STATE_VEHICLE_NOT_RESPONDING,
    SessionMonitor,
)
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mitsubishi Connect EU from a config entry."""
    # Der Monitor ueberlebt ein Neuladen des Eintrags (Optionen speichern): so bleibt
    # der 10-min-Backoff fuer automatische Neu-Logins erhalten.
    monitor = hass.data.setdefault(f"{DOMAIN}_sessions", {}).setdefault(entry.entry_id, SessionMonitor())
    client = MitsubishiEUClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        pin=entry.data.get(CONF_PIN, ""),
        session=monitor,
    )

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
            # VSR-Refresh triggern (Auto aufwecken → frische Daten an Server)
            # Dann mehrfach pollen bis frische Daten ankommen.
            # Sitzungsverlust: der Client meldet sich hoechstens einmal je 10 min
            # neu an (SessionMonitor); hier nur auswerten und den Grund melden.
            client.begin_cycle()
            try:
                refreshed = await client.async_refresh_status(v)
                if not refreshed:
                    _LOGGER.warning("VSR-Refresh fehlgeschlagen fuer %s, lese trotzdem Status", v)

                # Auto braucht Zeit zum Aufwachen (Mobilfunk-Modem, Verbindung).
                # Erste Abfrage nach 15s, dann alle 10s nochmal, max 90s warten.
                state = None
                for attempt in range(1, 8):
                    wait = 15 if attempt == 1 else 10
                    await asyncio.sleep(wait)
                    state = await client.async_get_vehicle_status(v)
                    if state.battery_level is not None or state.odometer is not None:
                        _LOGGER.debug(
                            "Frische Daten fuer %s nach %s Sekunden (Versuch %s)",
                            v, 15 + (attempt - 1) * 10 if attempt > 1 else 15, attempt,
                        )
                        monitor.set_state(STATE_OK)
                        return state

                # Nach 90s immer noch keine Daten: Grund trennen
                if state and (state.battery_level is None and state.odometer is None):
                    if monitor.state == STATE_NETWORK_ERROR:
                        raise UpdateFailed(
                            f"Keine Daten von der API erhalten fuer {v} nach 90s — Netzwerkfehler"
                        )
                    if client.last_status_valid:
                        monitor.set_state(STATE_VEHICLE_NOT_RESPONDING, "Fahrzeug antwortet nicht")
                        _LOGGER.warning(
                            "Fahrzeug antwortet nicht (Sitzung ok): keine Fahrzeugdaten nach 90 s"
                        )
                        raise UpdateFailed(
                            f"Fahrzeug antwortet nicht (Sitzung ok): keine Daten fuer {v} nach 90s"
                        )
                    monitor.set_state(STATE_SESSION_LOST, "keine gültige Antwort")
                    _LOGGER.warning(
                        "Keine gültige Antwort vom Server nach 90 s; Sitzung unklar, "
                        "kein Neu-Login (Sitzung lieferte seit dem Login noch nie Daten)"
                    )
                    raise UpdateFailed(
                        f"Keine gueltige Antwort vom Server fuer {v} nach 90s (Sitzung unklar)"
                    )
                return state
            except SessionLostError as err:
                if err.auth_rejected:
                    raise ConfigEntryAuthFailed(
                        "Mitsubishi Connect EU hat die Zugangsdaten abgelehnt"
                    ) from err
                raise UpdateFailed(str(err)) from err
            except (UpdateFailed, ConfigEntryAuthFailed):
                raise
            except Exception as err:
                raise UpdateFailed(f"Fehler beim Aktualisieren von {v}: {err}") from err

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{vin}",
            update_method=_update_vehicle,
            update_interval=update_interval,
        )
        await coordinator.async_config_entry_first_refresh()
        coordinators[vin] = coordinator

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
    gibt es keinen KeyError."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data is not None:
            await data["client"].async_close()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update-Listener: Neu laden ueber den HA-Lebenszyklus.

    Bis 1.0.8 rief der Listener async_unload_entry/async_setup_entry direkt auf,
    an HA vorbei: der Coordinator hatte keinen Config-Entry (ConfigEntryError im
    ersten Refresh bei jedem Speichern der Optionen), der Eintrag blieb fuer HA
    "geladen" und das naechste echte Entladen endete im KeyError."""
    hass.config_entries.async_schedule_reload(entry.entry_id)
