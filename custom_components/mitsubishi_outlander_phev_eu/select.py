"""Select entities for schedule day configuration (Mitsubishi Connect EU)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

DAYS_OPTIONS = [
    "daily",
    "weekdays",
    "weekend",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
DEFAULT_DAYS = "weekdays"


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
            entities.append(MitsubishiScheduleDaysEntity(vin, vehicle_info, "charge", slot))
            entities.append(MitsubishiScheduleDaysEntity(vin, vehicle_info, "climate", slot))
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


class MitsubishiScheduleDaysEntity(SelectEntity, RestoreEntity):
    """Wochentage eines Zeitplan-Slots — lokal gespeichert, überlebt Neustart."""

    _attr_has_entity_name = True
    _attr_options = DAYS_OPTIONS

    def __init__(self, vin: str, vehicle_info: dict, schedule_type: str, slot: int) -> None:
        self._vin = vin
        key = f"{schedule_type}_schedule_{slot}_days"
        self._attr_unique_id = f"{vin}_{key}"
        self._attr_translation_key = key
        self._attr_entity_registry_enabled_default = False
        self._attr_icon = "mdi:calendar-week"
        self._attr_device_info = _make_device_info(vin, vehicle_info)
        self._current_option: str = DEFAULT_DAYS

    @property
    def current_option(self) -> str:
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in DAYS_OPTIONS:
            self._current_option = last_state.state
