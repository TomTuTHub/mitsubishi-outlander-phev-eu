"""Sensors for Mitsubishi Connect EU."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity
from .api import VehicleState


@dataclass
class MitsubishiSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[VehicleState], any] = None


SENSOR_DESCRIPTIONS: tuple[MitsubishiSensorEntityDescription, ...] = (
    # =================================================================
    # PRIMARY — aktiv
    # =================================================================
    MitsubishiSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        value_fn=lambda s: s.battery_level,
    ),
    MitsubishiSensorEntityDescription(
        key="ev_range",
        translation_key="ev_range",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_fn=lambda s: s.ev_range,
    ),
    MitsubishiSensorEntityDescription(
        key="total_range",
        translation_key="total_range",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda s: s.total_range,
    ),
    MitsubishiSensorEntityDescription(
        key="charging_remaining_time",
        translation_key="charging_remaining_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_fn=lambda s: s.charging_remaining_time,
    ),
    # =================================================================
    # PRIMARY — deaktiviert
    # =================================================================
    MitsubishiSensorEntityDescription(
        key="fuel_range",
        translation_key="fuel_range",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fuel",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.fuel_range,
    ),
    MitsubishiSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.odometer,
    ),
    MitsubishiSensorEntityDescription(
        key="target_temperature",
        translation_key="target_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.target_temperature,
    ),
    # =================================================================
    # DIAGNOSTIC — aktiv
    # =================================================================
    MitsubishiSensorEntityDescription(
        key="battery_12v",
        translation_key="battery_12v",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:car-battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery_12v,
    ),
    MitsubishiSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.firmware_version,
    ),
    # =================================================================
    # DIAGNOSTIC — deaktiviert
    # =================================================================
    MitsubishiSensorEntityDescription(
        key="tire_fl_pressure",
        translation_key="tire_fl_pressure",
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:car-tire-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.tire_fl_pressure,
    ),
    MitsubishiSensorEntityDescription(
        key="tire_fr_pressure",
        translation_key="tire_fr_pressure",
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:car-tire-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.tire_fr_pressure,
    ),
    MitsubishiSensorEntityDescription(
        key="tire_rl_pressure",
        translation_key="tire_rl_pressure",
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:car-tire-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.tire_rl_pressure,
    ),
    MitsubishiSensorEntityDescription(
        key="tire_rr_pressure",
        translation_key="tire_rr_pressure",
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:car-tire-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.tire_rr_pressure,
    ),
    MitsubishiSensorEntityDescription(
        key="speed",
        translation_key="speed",
        native_unit_of_measurement="km/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.speed,
    ),
    MitsubishiSensorEntityDescription(
        key="charging_base_cost",
        translation_key="charging_base_cost",
        native_unit_of_measurement="ct/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:currency-eur",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.charging_base_cost,
    ),
    MitsubishiSensorEntityDescription(
        key="last_trip_distance",
        translation_key="last_trip_distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-path",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.last_trip_distance,
    ),
    MitsubishiSensorEntityDescription(
        key="last_trip_duration",
        translation_key="last_trip_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.last_trip_duration,
    ),
    MitsubishiSensorEntityDescription(
        key="last_charge_energy",
        translation_key="last_charge_energy",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.last_charge_energy,
    ),
    MitsubishiSensorEntityDescription(
        key="last_charge_duration",
        translation_key="last_charge_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.last_charge_duration,
    ),
)


def _build_vehicle_status(state: VehicleState) -> dict[str, Any]:
    """Baut die extra_state_attributes für den vehicle_status Sensor."""
    _DOOR_LABELS = {
        "door_fl": "Door Front Left", "door_fr": "Door Front Right",
        "door_rl": "Door Rear Left", "door_rr": "Door Rear Right",
        "hood": "Hood", "trunk": "Trunk",
    }
    _WIN_LABELS = {
        "window_fl": "Window Front Left", "window_fr": "Window Front Right",
        "window_rl": "Window Rear Left", "window_rr": "Window Rear Right",
        "sunroof": "Sunroof",
    }
    attrs: dict[str, str] = {}
    for key, label in _DOOR_LABELS.items():
        val = getattr(state, f"{key}_open", False)
        attrs[label] = "open" if val else "closed"
    for key, label in _WIN_LABELS.items():
        val = getattr(state, f"{key}_open", False)
        attrs[label] = "open" if val else "closed"
    attrs["Headlights"] = "on" if state.headlights_on else "off"
    attrs["Locked"] = "locked" if state.doors_locked else "unlocked" if state.doors_locked is False else "unknown"
    return attrs


_OPEN_LABELS = {
    "door_fl_open": "Door FL", "door_fr_open": "Door FR",
    "door_rl_open": "Door RL", "door_rr_open": "Door RR",
    "door_hood_open": "Hood", "door_trunk_open": "Trunk",
    "window_fl_open": "Window FL", "window_fr_open": "Window FR",
    "window_rl_open": "Window RL", "window_rr_open": "Window RR",
    "window_sunroof_open": "Sunroof",
}


def _vehicle_status_state(state: VehicleState) -> str:
    """Hauptwert: 'OK' oder kommagetrennte Liste offener Türen/Fenster."""
    open_names = [label for attr, label in _OPEN_LABELS.items()
                  if getattr(state, attr, False)]
    if not open_names:
        return "OK"
    return ", ".join(open_names)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for vin, coordinator in data["coordinators"].items():
        vehicle_info = next(
            (v for v in data["vehicles"] if v.get("vin") == vin), {}
        )
        for description in SENSOR_DESCRIPTIONS:
            entities.append(MitsubishiSensor(coordinator, vin, vehicle_info, description))
        entities.append(MitsubishiVehicleStatusSensor(coordinator, vin, vehicle_info))
    async_add_entities(entities)


class MitsubishiSensor(MitsubishiEUEntity, SensorEntity):
    entity_description: MitsubishiSensorEntityDescription

    def __init__(self, coordinator, vin, vehicle_info, description):
        super().__init__(coordinator, vin, vehicle_info)
        self.entity_description = description
        self._attr_unique_id = f"{vin}_{description.key}"

    @property
    def native_value(self):
        if self.vehicle_state is None:
            return None
        return self.entity_description.value_fn(self.vehicle_state)


class MitsubishiVehicleStatusSensor(MitsubishiEUEntity, SensorEntity):
    """Zusammenfassung: Türen, Fenster, Licht, Schloss als Attribute."""

    _attr_has_entity_name = True
    _attr_translation_key = "vehicle_status"
    _attr_icon = "mdi:car-info"

    def __init__(self, coordinator, vin, vehicle_info):
        super().__init__(coordinator, vin, vehicle_info)
        self._attr_unique_id = f"{vin}_vehicle_status"

    @property
    def native_value(self) -> str | None:
        if self.vehicle_state is None:
            return None
        return _vehicle_status_state(self.vehicle_state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.vehicle_state is None:
            return None
        return _build_vehicle_status(self.vehicle_state)
