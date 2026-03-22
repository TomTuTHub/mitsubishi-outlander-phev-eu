"""Buttons (einmalige Remote-Commands) for Mitsubishi Connect EU."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity

_LOGGER = logging.getLogger(__name__)


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
            MitsubishiHornButton(coordinator, vin, vehicle_info, client),
            MitsubishiLightsButton(coordinator, vin, vehicle_info, client),
            MitsubishiRefreshButton(coordinator, vin, vehicle_info, client),
        ]
    async_add_entities(entities)


class MitsubishiHornButton(MitsubishiEUEntity, ButtonEntity):
    """Hupen."""
    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_horn"
        self._attr_translation_key = "horn"
        self._attr_icon = "mdi:bugle"

    async def async_press(self) -> None:
        await self._client.async_horn(self._vin)


class MitsubishiLightsButton(MitsubishiEUEntity, ButtonEntity):
    """Lichter blinken."""
    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_lights"
        self._attr_translation_key = "lights"
        self._attr_icon = "mdi:car-light-high"

    async def async_press(self) -> None:
        await self._client.async_lights(self._vin)


class MitsubishiRefreshButton(MitsubishiEUEntity, ButtonEntity):
    """Fahrzeugstatus manuell aktualisieren (refreshVSR)."""
    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_refresh"
        self._attr_translation_key = "refresh"
        self._attr_icon = "mdi:refresh"

    async def async_press(self) -> None:
        if await self._client.async_refresh_status(self._vin):
            await self.coordinator.async_request_refresh()
