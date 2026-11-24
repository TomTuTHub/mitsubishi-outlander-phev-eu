"""Climate entity for Mitsubishi Connect EU — AC mit Temperaturregelung."""
from __future__ import annotations

import asyncio

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import MitsubishiEUEntity, raise_command_rejected

DELAYED_REFRESH = 15  # Sekunden warten bevor Status aktualisiert wird

MIN_TEMP = 16.0
MAX_TEMP = 28.0
TEMP_STEP = 0.5
DEFAULT_TEMP = 20.0


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
        entities.append(MitsubishiClimateEntity(coordinator, vin, vehicle_info, client))
    async_add_entities(entities)


class MitsubishiClimateEntity(MitsubishiEUEntity, ClimateEntity):
    """Klimaanlage mit Temperatursteuerung."""

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP
    _attr_icon = "mdi:air-conditioner"
    _attr_translation_key = "climate"

    def __init__(self, coordinator, vin, vehicle_info, client):
        super().__init__(coordinator, vin, vehicle_info)
        self._client = client
        self._attr_unique_id = f"{vin}_climate_control"
        self._optimistic_mode: HVACMode | None = None
        self._optimistic_temp: float | None = None

    @property
    def hvac_mode(self) -> HVACMode:
        if self._optimistic_mode is not None:
            return self._optimistic_mode
        if self.vehicle_state and self.vehicle_state.ac_on:
            return HVACMode.HEAT_COOL
        return HVACMode.OFF

    @property
    def target_temperature(self) -> float | None:
        if self._optimistic_temp is not None:
            return self._optimistic_temp
        if self.vehicle_state:
            return self.vehicle_state.target_temperature
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """b10: Ergebnis des letzten Klimabefehls, wie am Klima-Schalter."""
        last = getattr(self._client, "last_climate_command", {}).get(self._vin)
        return {"last_command": dict(last)} if last else None

    async def _async_command(self, mode: HVACMode, temp: float | None, call, command: str) -> None:
        """b10: sofort optimistisch anzeigen, dann das echte Ergebnis abwarten (Wecken +
        requestId-Polling im Client). Fehler oder keine Antwort: zurueck auf den alten
        Zustand und verstaendliche Fehlermeldung."""
        self._optimistic_mode = mode
        self._optimistic_temp = temp
        self.async_write_ha_state()
        try:
            ok = await call()
        except Exception:
            ok = None
            raise
        finally:
            if not ok:
                self._optimistic_mode = None
                self._optimistic_temp = None
                self.async_write_ha_state()
        if not ok:
            raise_command_rejected(self._client, self._vin, command)
        await asyncio.sleep(DELAYED_REFRESH)
        await self.coordinator.async_request_refresh()
        self._optimistic_mode = None
        self._optimistic_temp = None
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT_COOL:
            temp = self.target_temperature or DEFAULT_TEMP
            await self._async_command(
                HVACMode.HEAT_COOL, temp,
                lambda: self._client.async_start_climate(self._vin, temperature=temp),
                "startClimate")
        elif hvac_mode == HVACMode.OFF:
            await self._async_command(
                HVACMode.OFF, None,
                lambda: self._client.async_stop_climate(self._vin),
                "stopClimate")

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        # Klimaanlage starten (oder Temperatur aktualisieren wenn schon an)
        await self._async_command(
            HVACMode.HEAT_COOL, temperature,
            lambda: self._client.async_start_climate(self._vin, temperature=temperature),
            "startClimate")
