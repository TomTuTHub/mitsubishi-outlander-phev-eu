"""Lock entity for Mitsubishi Connect EU — Tuerverriegelung."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity

_LOGGER = logging.getLogger(__name__)

DELAYED_REFRESH = 15


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
        entities.append(MitsubishiDoorLock(coordinator, vin, vehicle_info, client))
    async_add_entities(entities)


class MitsubishiDoorLock(MitsubishiEUEntity, LockEntity):
    """Tuerverriegelung."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_door_lock"
        self._attr_translation_key = "door_lock"
        self._attr_icon = "mdi:car-door-lock"
        self._optimistic_state: bool | None = None

    @property
    def is_locked(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        # doorLockSts ist oft leer — dann "locked" annehmen statt None (ausgegraut)
        if self.vehicle_state.doors_locked is None:
            return True
        return self.vehicle_state.doors_locked

    async def async_lock(self, **kwargs) -> None:
        if await self._client.async_lock_doors(self._vin):
            self._optimistic_state = True
            self.async_write_ha_state()
            await asyncio.sleep(DELAYED_REFRESH)
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs) -> None:
        if await self._client.async_unlock_doors(self._vin):
            self._optimistic_state = False
            self.async_write_ha_state()
            await asyncio.sleep(DELAYED_REFRESH)
            self._optimistic_state = None
            await self.coordinator.async_request_refresh()
