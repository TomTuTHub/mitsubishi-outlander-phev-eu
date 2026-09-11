"""Data update coordinator helper for Mitsubishi Connect EU."""
from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def raise_command_rejected(client, vin: str, command: str) -> None:
    """Abgelehnten Remote-Befehl laut melden — nie still schlucken.

    Der Nutzertext kommt uebersetzt aus strings.json ("exceptions") und nennt
    den Cloud-Fehlercode des letzten POSTs; die Log-Zeile bleibt englisch und
    nennt zusaetzlich die VIN. Wird von switch.py und button.py genutzt.
    """
    code = getattr(client, "last_error_code", None) or "unknown"
    _LOGGER.error(
        "Mitsubishi Connect rejected remote command %s for VIN %s (error %s)",
        command,
        vin,
        code,
    )
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_rejected",
        translation_placeholders={"command": command, "code": code},
    )


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
