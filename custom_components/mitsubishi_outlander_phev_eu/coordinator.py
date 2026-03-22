"""Data update coordinator helper for Mitsubishi Connect EU."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class MitsubishiEUEntity(CoordinatorEntity):
    """Base entity class for Mitsubishi Connect EU."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, vin: str, vehicle_info: dict) -> None:
        super().__init__(coordinator)
        self._vin = vin
        self._vehicle_info = vehicle_info

        nick = vehicle_info.get("nickName", "")
        model_data = vehicle_info.get("model", {})
        if isinstance(model_data, dict):
            model_name = model_data.get("bodyWork", "Outlander PHEV")
            model_year = model_data.get("modelYear", "")
        else:
            model_name = "Outlander PHEV"
            model_year = ""

        display_name = nick or f"Mitsubishi {vin[-6:]}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, vin)},
            name=display_name,
            manufacturer="Mitsubishi Motors",
            model=f"{model_name} {model_year}".strip(),
            serial_number=vin,
        )

    @property
    def vehicle_state(self):
        """Return latest vehicle state from coordinator."""
        return self.coordinator.data
