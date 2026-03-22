"""Switches (remote commands) for Mitsubishi Connect EU."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity

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
        entities += [
            MitsubishiClimateSwitch(coordinator, vin, vehicle_info, client),
            MitsubishiChargeSwitch(coordinator, vin, vehicle_info, client),
        ]
    async_add_entities(entities)


class MitsubishiClimateSwitch(MitsubishiEUEntity, SwitchEntity):
    """Klimaanlage fernsteuern."""

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

    async def async_turn_on(self, **kwargs) -> None:
        if await self._client.async_start_climate(self._vin):
            self._optimistic_state = True
            self.async_write_ha_state()
            await asyncio.sleep(DELAYED_REFRESH)
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        if await self._client.async_stop_climate(self._vin):
            self._optimistic_state = False
            self.async_write_ha_state()
            await asyncio.sleep(DELAYED_REFRESH)
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()


class MitsubishiChargeSwitch(MitsubishiEUEntity, SwitchEntity):
    """Laden fernsteuern."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_charging"
        self._attr_translation_key = "charging"
        self._attr_icon = "mdi:ev-station"
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        return self.vehicle_state.is_charging

    async def async_turn_on(self, **kwargs) -> None:
        if await self._client.async_start_charging(self._vin):
            self._optimistic_state = True
            self.async_write_ha_state()
            await asyncio.sleep(DELAYED_REFRESH)
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        if await self._client.async_stop_charging(self._vin):
            self._optimistic_state = False
            self.async_write_ha_state()
            await asyncio.sleep(DELAYED_REFRESH)
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()
