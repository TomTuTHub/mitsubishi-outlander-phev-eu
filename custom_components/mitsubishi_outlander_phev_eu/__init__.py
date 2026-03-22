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

from .api import MitsubishiEUClient, VehicleState
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
    client = MitsubishiEUClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        pin=entry.data.get(CONF_PIN, ""),
    )

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
            # VSR-Refresh triggern (Auto aufwecken → frische Daten an Server)
            # Dann mehrfach pollen bis frische Daten ankommen
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
                        return state

                # Nach 90s immer noch keine Daten
                if state and (state.battery_level is None and state.odometer is None):
                    raise UpdateFailed(
                        f"Keine Daten von der API erhalten fuer {v} nach 90s — "
                        "Fahrzeug antwortet nicht oder Session abgelaufen"
                    )
                return state
            except UpdateFailed:
                raise
            except Exception as err:
                raise UpdateFailed(f"Fehler beim Aktualisieren von {v}: {err}") from err

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
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
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].async_close()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
