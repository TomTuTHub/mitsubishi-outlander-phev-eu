"""Switches (remote commands) for Mitsubishi Connect EU."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity, raise_command_rejected

_LOGGER = logging.getLogger(__name__)
DELAYED_REFRESH = 15  # Sekunden warten bevor Status aktualisiert wird


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for vin, coordinator in data["coordinators"].items():
        vehicle_info = next((v for v in data["vehicles"] if v.get("vin") == vin), {})
        client = data["client"]
        _async_remove_charge_switch(hass, vin)
        entities.append(MitsubishiClimateSwitch(coordinator, vin, vehicle_info, client))
    async_add_entities(entities)


def _async_remove_charge_switch(hass: HomeAssistant, vin: str) -> None:
    """Den alten Lade-Switch aus der Registry raeumen.

    Seit v1.0.5 gibt es statt des Schalters den Button "Laden starten": die
    Mitsubishi-Cloud kennt keinen Fern-Ladestopp (verifiziert 2026-09-10 am
    ladenden Fahrzeug, errorCode 950400), ein Schalter mit funktionsloser
    Aus-Seite waere gelogen. Der Ladestatus steht im Binary Sensor.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{vin}_charging")
    if entity_id:
        _LOGGER.info(
            "Entferne veralteten Lade-Schalter %s — ersetzt durch den Button "
            "'Laden starten' (die Cloud kann Laden nicht fern-stoppen)",
            entity_id,
        )
        registry.async_remove(entity_id)


class MitsubishiClimateSwitch(MitsubishiEUEntity, SwitchEntity):
    """Klimaanlage fernsteuern (kann echt an UND aus)."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_climate"
        self._attr_translation_key = "climate"
        self._attr_icon = "mdi:air-conditioner"
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        return self.vehicle_state.ac_on

    async def _async_settle(self, state: bool) -> None:
        """Optimistisch anzeigen, Refresh abwarten, dann echten Wert uebernehmen.

        Der optimistische Wert wird erst NACH dem Refresh verworfen — sonst
        zeigt die UI waehrend des laufenden Refreshs (15-90 s) wieder den
        alten Coordinator-Wert und der Schalter springt zurueck.
        """
        self._optimistic_state = state
        self.async_write_ha_state()
        await asyncio.sleep(DELAYED_REFRESH)
        await self.coordinator.async_request_refresh()
        self._optimistic_state = None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        if not await self._client.async_start_climate(self._vin):
            raise_command_rejected(self._client, self._vin, "startClimate")
        await self._async_settle(True)

    async def async_turn_off(self, **kwargs) -> None:
        if not await self._client.async_stop_climate(self._vin):
            raise_command_rejected(self._client, self._vin, "stopClimate")
        await self._async_settle(False)
