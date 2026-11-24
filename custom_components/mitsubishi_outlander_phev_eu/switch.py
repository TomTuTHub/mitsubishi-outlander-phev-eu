"""Switches (remote commands) for Mitsubishi Connect EU."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity, raise_command_rejected

_LOGGER = logging.getLogger(__name__)
DELAYED_REFRESH = 15  # Sekunden warten bevor Status aktualisiert wird


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
        _async_remove_charge_switch(hass, vin)
        entities.append(MitsubishiClimateSwitch(coordinator, vin, vehicle_info, client))
        entities.append(MitsubishiRemoteEngineSwitch(coordinator, vin, vehicle_info, client))
    async_add_entities(entities)


def _async_remove_charge_switch(hass: HomeAssistant, vin: str) -> None:
    """Den alten Lade-Switch aus der Registry raeumen.

    Seit v1.0.5 gibt es statt des Schalters den Button "Laden starten": die
    Mitsubishi-Cloud kennt keinen Fern-Ladestopp (verifiziert 2026-09-10 am
    ladenden Fahrzeug, errorCode 950400), ein Schalter mit funktionsloser
    Aus-Seite waere gelogen. Der Ladestatus steht im Binary Sensor.
    """
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{vin}_charging")
    if entity_id:
        _LOGGER.info(
            "Entferne veralteten Lade-Schalter %s — ersetzt durch den Button "
            "'Laden starten' (die Cloud kann Laden nicht fern-stoppen)",
            entity_id,
        )
        registry.async_remove(entity_id)


class MitsubishiClimateSwitch(MitsubishiEUEntity, SwitchEntity):
    """Klimaanlage fernsteuern (kann echt an UND aus)."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_climate"
        self._attr_translation_key = "climate"
        self._attr_icon = "mdi:air-conditioner"
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        return self.vehicle_state.ac_on

    @property
    def extra_state_attributes(self) -> dict | None:
        """b10: Ergebnis des letzten Klimabefehls (command, result, request_id, status,
        error, at). result: ok | rejected | no_response | accepted_no_request_id | failed."""
        last = getattr(self._client, "last_climate_command", {}).get(self._vin)
        return {"last_command": dict(last)} if last else None

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

    async def _async_command(self, state: bool, call, command: str) -> None:
        """b10: sofort optimistisch schalten, dann das echte Ergebnis abwarten
        (Wecken + requestId-Polling im Client, bis zu duration). Lehnt das Auto ab
        oder antwortet nicht, faellt der Schalter auf den alten Zustand zurueck."""
        self._optimistic_state = state
        self.async_write_ha_state()
        try:
            ok = await call(self._vin)
        except Exception:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise
        if not ok:
            self._optimistic_state = None
            self.async_write_ha_state()
            raise_command_rejected(self._client, self._vin, command)
        await self._async_settle(state)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_command(True, self._client.async_start_climate, "startClimate")

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_command(False, self._client.async_stop_climate, "stopClimate")


ENGINE_WARNING = "Startet beim PHEV möglicherweise den Benzinmotor. Nur zur Diagnose."


class MitsubishiRemoteEngineSwitch(MitsubishiClimateSwitch):
    """b11, NUR DIAGNOSE (standardmaessig deaktiviert): Motor-Remote-Einschaltung (Vorklimatisierung ueber startEngine).

    Gleicher Ablauf und gleicher Body wie der Klima-Schalter (Wecken mit Sperre,
    frische Nonce und pinHash, targetTemperature als String, temperatureUnit C,
    hvacSettings, requestId-Polling, kein Nachversuch); nur der Endpunkt ist
    startEngine/stopEngine. Laut Mitsubishi-Mails der Weg, der zuletzt geklappt hat."""

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info, client)
        self._attr_unique_id = f"{vin}_remote_engine"
        self._attr_translation_key = "remote_engine"
        self._attr_icon = "mdi:engine"
        # Nur Diagnosewerkzeug: startEngine kann beim PHEV den Benzinmotor starten
        self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        if self.vehicle_state is None:
            return None
        return self.vehicle_state.engine_on

    @property
    def extra_state_attributes(self) -> dict | None:
        last = getattr(self._client, "last_engine_command", {}).get(self._vin)
        attrs = {"warning": ENGINE_WARNING}
        if last:
            attrs["last_command"] = dict(last)
        return attrs

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_command(True, self._client.async_start_engine, "startEngine")

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_command(False, self._client.async_stop_engine, "stopEngine")
