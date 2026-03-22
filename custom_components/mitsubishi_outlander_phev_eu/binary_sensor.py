"""Binary sensors for Mitsubishi Connect EU."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity
from .api import VehicleState


@dataclass
class MitsubishiBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[VehicleState], bool | None] = None


BINARY_SENSOR_DESCRIPTIONS: tuple[MitsubishiBinarySensorDescription, ...] = (
    # =================================================================
    # PRIMARY — aktiv
    # =================================================================
    MitsubishiBinarySensorDescription(
        key="is_charging",
        translation_key="is_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        icon="mdi:battery-charging",
        value_fn=lambda s: s.is_charging,
    ),
    MitsubishiBinarySensorDescription(
        key="is_plugged_in",
        translation_key="is_plugged_in",
        device_class=BinarySensorDeviceClass.PLUG,
        icon="mdi:power-plug",
        value_fn=lambda s: s.is_plugged_in,
    ),
    MitsubishiBinarySensorDescription(
        key="doors_locked",
        translation_key="doors_locked",
        device_class=BinarySensorDeviceClass.LOCK,
        icon="mdi:car-door-lock",
        value_fn=lambda s: not s.doors_locked if s.doors_locked is not None else False,
    ),
    # =================================================================
    # PRIMARY — deaktiviert
    # =================================================================
    MitsubishiBinarySensorDescription(
        key="engine_on",
        translation_key="engine_on",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:engine",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.engine_on,
    ),
    MitsubishiBinarySensorDescription(
        key="ac_on",
        translation_key="ac_on",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:air-conditioner",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.ac_on,
    ),
    # --- Türen einzeln (deaktiviert, Infos auch im vehicle_status Sensor) ---
    MitsubishiBinarySensorDescription(
        key="door_fl_open",
        translation_key="door_fl_open",
        device_class=BinarySensorDeviceClass.DOOR,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.door_fl_open,
    ),
    MitsubishiBinarySensorDescription(
        key="door_fr_open",
        translation_key="door_fr_open",
        device_class=BinarySensorDeviceClass.DOOR,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.door_fr_open,
    ),
    MitsubishiBinarySensorDescription(
        key="door_rl_open",
        translation_key="door_rl_open",
        device_class=BinarySensorDeviceClass.DOOR,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.door_rl_open,
    ),
    MitsubishiBinarySensorDescription(
        key="door_rr_open",
        translation_key="door_rr_open",
        device_class=BinarySensorDeviceClass.DOOR,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.door_rr_open,
    ),
    MitsubishiBinarySensorDescription(
        key="door_hood_open",
        translation_key="door_hood_open",
        device_class=BinarySensorDeviceClass.DOOR,
        icon="mdi:car-lifted-pickup",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.door_hood_open,
    ),
    MitsubishiBinarySensorDescription(
        key="door_trunk_open",
        translation_key="door_trunk_open",
        device_class=BinarySensorDeviceClass.DOOR,
        icon="mdi:car-back",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.door_trunk_open,
    ),
    # --- Fenster einzeln (deaktiviert, Infos auch im vehicle_status Sensor) ---
    MitsubishiBinarySensorDescription(
        key="window_fl_open",
        translation_key="window_fl_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.window_fl_open,
    ),
    MitsubishiBinarySensorDescription(
        key="window_fr_open",
        translation_key="window_fr_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.window_fr_open,
    ),
    MitsubishiBinarySensorDescription(
        key="window_rl_open",
        translation_key="window_rl_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.window_rl_open,
    ),
    MitsubishiBinarySensorDescription(
        key="window_rr_open",
        translation_key="window_rr_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:car-door",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.window_rr_open,
    ),
    MitsubishiBinarySensorDescription(
        key="window_sunroof_open",
        translation_key="window_sunroof_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:window-open-variant",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.window_sunroof_open,
    ),
    # =================================================================
    # DIAGNOSTIC — deaktiviert
    # =================================================================
    MitsubishiBinarySensorDescription(
        key="headlights_on",
        translation_key="headlights_on",
        device_class=BinarySensorDeviceClass.LIGHT,
        icon="mdi:car-light-high",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.headlights_on,
    ),
    MitsubishiBinarySensorDescription(
        key="brake_warning",
        translation_key="brake_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-brake-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.brake_warning,
    ),
    MitsubishiBinarySensorDescription(
        key="engine_oil_warning",
        translation_key="engine_oil_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:oil",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.engine_oil_warning,
    ),
    MitsubishiBinarySensorDescription(
        key="mil_warning",
        translation_key="mil_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:engine-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.mil_warning,
    ),
    MitsubishiBinarySensorDescription(
        key="abs_warning",
        translation_key="abs_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:car-brake-abs",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.abs_warning,
    ),
    MitsubishiBinarySensorDescription(
        key="airbag_warning",
        translation_key="airbag_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:airbag",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.airbag_warning,
    ),
    MitsubishiBinarySensorDescription(
        key="charging_ready",
        translation_key="charging_ready",
        icon="mdi:battery-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.charging_ready,
    ),
    MitsubishiBinarySensorDescription(
        key="charge_disabled",
        translation_key="charge_disabled",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:battery-off",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.charge_disabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for vin, coordinator in data["coordinators"].items():
        vehicle_info = next((v for v in data["vehicles"] if v.get("vin") == vin), {})
        for description in BINARY_SENSOR_DESCRIPTIONS:
            entities.append(MitsubishiBinarySensor(coordinator, vin, vehicle_info, description))
    async_add_entities(entities)


class MitsubishiBinarySensor(MitsubishiEUEntity, BinarySensorEntity):
    entity_description: MitsubishiBinarySensorDescription

    def __init__(self, coordinator, vin, vehicle_info, description):
        super().__init__(coordinator, vin, vehicle_info)
        self.entity_description = description
        self._attr_unique_id = f"{vin}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        if self.vehicle_state is None:
            return None
        return self.entity_description.value_fn(self.vehicle_state)
