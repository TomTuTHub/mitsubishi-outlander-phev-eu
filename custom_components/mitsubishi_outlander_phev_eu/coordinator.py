"""Data update coordinator helper for Mitsubishi Connect EU."""
from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_SOURCE, ERR_VEHICLE_NO_RESPONSE, ERR_VEHICLE_REJECTED

_LOGGER = logging.getLogger(__name__)


def raise_command_rejected(client, vin: str, command: str) -> None:
    """Abgelehnten Remote-Befehl laut melden — nie still schlucken.

    Der Nutzertext kommt uebersetzt aus strings.json ("exceptions") und nennt
    den Cloud-Fehlercode des letzten POSTs; die Log-Zeile bleibt englisch und
    nennt zusaetzlich die requestId (seit b10 ohne VIN). Wird von switch.py,
    climate.py und button.py genutzt.

    Seit b10 zwei eigene Texte fuer das Ergebnis des requestId-Pollings:
    "vehicle_no_response" (Auto hat bis duration nicht geantwortet) und
    "vehicle_rejected:<status>" (Auto hat den Befehl abgelehnt).
    """
    code = getattr(client, "last_error_code", None) or "unknown"
    request_id = getattr(client, "last_request_id", None) or "-"
    _LOGGER.error(
        "Mitsubishi Connect remote command %s failed (error %s, requestId %s)",
        command,
        code,
        request_id,
    )
    if code == ERR_VEHICLE_NO_RESPONSE:
        key, placeholders = "vehicle_no_response", {"command": command}
    elif code.startswith(ERR_VEHICLE_REJECTED + ":"):
        key = "vehicle_rejected"
        placeholders = {"command": command, "status": code.split(":", 1)[1]}
    else:
        key, placeholders = "command_rejected", {"command": command, "code": code}
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
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

    # Quelle fuer Entities ohne entity_description (z. B. Tracker, Statuszusammenfassung)
    _source: str | None = None

    @property
    def available(self) -> bool:
        """Unavailable, wenn der zugehoerige Status-Endpoint technisch ausgefallen ist."""
        if not super().available:
            return False
        state = self.coordinator.data
        failed = getattr(state, "failed_sources", None)
        if not failed:
            return True
        key = getattr(getattr(self, "entity_description", None), "key", None)
        source = self._source or ENTITY_SOURCE.get(key)
        return source not in failed

    @property
    def vehicle_state(self):
        """Return latest vehicle state from coordinator."""
        return self.coordinator.data
