"""Device tracker for Mitsubishi Connect EU."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for vin, coordinator in data["coordinators"].items():
        vehicle_info = next((v for v in data["vehicles"] if v.get("vin") == vin), {})
        entities.append(MitsubishiDeviceTracker(coordinator, vin, vehicle_info))
    async_add_entities(entities)


class MitsubishiDeviceTracker(MitsubishiEUEntity, TrackerEntity):
    """Track vehicle location."""

    def __init__(self, coordinator, vin, vehicle_info):
        super().__init__(coordinator, vin, vehicle_info)
        self._attr_unique_id = f"{vin}_location"
        self._attr_translation_key = "location"
        self._attr_icon = "mdi:car"

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        if self.vehicle_state is None:
            return None
        lat = self.vehicle_state.location.latitude
        return float(lat) if lat is not None else None

    @property
    def longitude(self) -> float | None:
        if self.vehicle_state is None:
            return None
        lon = self.vehicle_state.location.longitude
        return float(lon) if lon is not None else None
