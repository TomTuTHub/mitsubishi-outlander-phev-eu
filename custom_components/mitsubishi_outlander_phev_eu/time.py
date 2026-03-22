"""Time entities for schedule start time configuration (Mitsubishi Connect EU)."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_DEFAULT_TIME = {"charge": "22:00", "climate": "07:30"}
_ICON = {"charge": "mdi:clock-end", "climate": "mdi:clock-start"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for vin, _coordinator in data["coordinators"].items():
        vehicle_info = next((v for v in data["vehicles"] if v.get("vin") == vin), {})
        for slot in [1, 2, 3]:
            entities.append(MitsubishiScheduleTimeEntity(vin, vehicle_info, "charge", slot))
            entities.append(MitsubishiScheduleTimeEntity(vin, vehicle_info, "climate", slot))
    async_add_entities(entities)


def _make_device_info(vin: str, vehicle_info: dict) -> DeviceInfo:
    nick = vehicle_info.get("nickName", "")
    model_data = vehicle_info.get("model", {})
    if isinstance(model_data, dict):
        model_name = model_data.get("bodyWork", "Outlander PHEV")
        model_year = model_data.get("modelYear", "")
    else:
        model_name = "Outlander PHEV"
        model_year = ""
    return DeviceInfo(
        identifiers={(DOMAIN, vin)},
        name=nick or f"Mitsubishi {vin[-6:]}",
        manufacturer="Mitsubishi Motors",
        model=f"{model_name} {model_year}".strip(),
        serial_number=vin,
    )


class MitsubishiScheduleTimeEntity(TimeEntity, RestoreEntity):
    """Startzeit eines Zeitplan-Slots — lokal gespeichert, überlebt Neustart."""

    _attr_has_entity_name = True

    def __init__(self, vin: str, vehicle_info: dict, schedule_type: str, slot: int) -> None:
        self._vin = vin
        key = f"{schedule_type}_schedule_{slot}_time"
        self._attr_unique_id = f"{vin}_{key}"
        self._attr_translation_key = key
        self._attr_entity_registry_enabled_default = False
        self._attr_icon = _ICON[schedule_type]
        self._attr_device_info = _make_device_info(vin, vehicle_info)
        h, m = map(int, _DEFAULT_TIME[schedule_type].split(":"))
        self._value: time = time(h, m)

    @property
    def native_value(self) -> time | None:
        return self._value

    async def async_set_value(self, value: time) -> None:
        self._value = value
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unavailable", "unknown"):
            try:
                parts = last_state.state.split(":")
                self._value = time(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
