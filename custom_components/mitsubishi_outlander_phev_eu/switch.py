"""Switches (remote commands) for Mitsubishi Connect EU."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity

_LOGGER = logging.getLogger(__name__)
DELAYED_REFRESH = 15  # Sekunden warten bevor Status aktualisiert wird

# Verifiziert 2026-09-10 am ladenden Fahrzeug: POST /remote/stopCharge/v1
# wird von der EU-Cloud sofort mit errorCode 950400 abgelehnt; auch die
# offizielle App bietet waehrend des Ladens keinen Stopp an. Trotzdem wird
# hier kein Sonderfall gebaut — der Code wird generisch gemeldet, damit die
# Meldung stimmt, falls Mitsubishi den Befehl spaeter freischaltet oder aus
# anderem Grund ablehnt. Texte: strings.json/translations, "exceptions".


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
            MitsubishiClimateSwitch(coordinator, vin, vehicle_info, client),
            MitsubishiChargeSwitch(coordinator, vin, vehicle_info, client),
        ]
    async_add_entities(entities)


class MitsubishiRemoteSwitch(MitsubishiEUEntity, SwitchEntity):
    """Basis fuer Schalter, die einen Remote-Befehl an die Cloud schicken."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._optimistic_state: bool | None = None

    async def _async_settle(self, state: bool) -> None:
        """Optimistisch anzeigen, Refresh abwarten, dann echten Wert uebernehmen.

        Der optimistische Wert wird erst NACH dem Refresh verworfen — sonst
        zeigt die UI waehrend des laufenden Refreshs (15-90 s) wieder den
        alten Coordinator-Wert und der Schalter springt zurueck.
        """
        self._optimistic_state = state
        self.async_write_ha_state()
        await asyncio.sleep(DELAYED_REFRESH)
        await self.coordinator.async_request_refresh()
        self._optimistic_state = None
        self.async_write_ha_state()

    def _reject(self, command: str) -> None:
        """Abgelehnten Remote-Befehl laut melden — nie still schlucken.

        Der Nutzertext kommt uebersetzt aus strings.json ("exceptions") und
        nennt den Cloud-Fehlercode des letzten POSTs; die Log-Zeile bleibt
        englisch und nennt zusaetzlich die VIN.
        """
        code = getattr(self._client, "last_error_code", None) or "unknown"
        _LOGGER.error(
            "Mitsubishi Connect rejected remote command %s for VIN %s (error %s)",
            command,
            self._vin,
            code,
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_rejected",
            translation_placeholders={"command": command, "code": code},
        )


class MitsubishiClimateSwitch(MitsubishiRemoteSwitch):
    """Klimaanlage fernsteuern."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info, client)
        self._attr_unique_id = f"{vin}_climate"
        self._attr_translation_key = "climate"
        self._attr_icon = "mdi:air-conditioner"

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        return self.vehicle_state.ac_on

    async def async_turn_on(self, **kwargs) -> None:
        if not await self._client.async_start_climate(self._vin):
            self._reject("startClimate")
        await self._async_settle(True)

    async def async_turn_off(self, **kwargs) -> None:
        if not await self._client.async_stop_climate(self._vin):
            self._reject("stopClimate")
        await self._async_settle(False)


class MitsubishiChargeSwitch(MitsubishiRemoteSwitch):
    """Laden fernsteuern (Start/Stopp, soweit die Cloud den Befehl annimmt)."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info, client)
        self._attr_unique_id = f"{vin}_charging"
        self._attr_translation_key = "charging"
        self._attr_icon = "mdi:ev-station"

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        return self.vehicle_state.is_charging

    async def async_turn_on(self, **kwargs) -> None:
        if not await self._client.async_start_charging(self._vin):
            self._reject("startCharge")
        await self._async_settle(True)

    async def async_turn_off(self, **kwargs) -> None:
        if not await self._client.async_stop_charging(self._vin):
            self._reject("stopCharge")
        await self._async_settle(False)
