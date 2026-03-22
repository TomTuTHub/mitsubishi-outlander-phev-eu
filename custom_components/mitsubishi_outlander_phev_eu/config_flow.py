"""Config flow for Mitsubishi Connect EU."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import MitsubishiEUClient
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_TEXT = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_NUMBER = NumberSelector(NumberSelectorConfig(
    min=MIN_UPDATE_INTERVAL, max=120, step=1, mode=NumberSelectorMode.BOX
))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): _TEXT,
        vol.Required(CONF_PASSWORD): _PASSWORD,
        vol.Required(CONF_PIN): _PASSWORD,
        vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): _NUMBER,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    client = MitsubishiEUClient(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        pin=data.get(CONF_PIN, ""),
    )
    try:
        if not await client.async_login():
            raise InvalidAuth
        vehicles = await client.async_get_vehicles()
        if not vehicles:
            raise NoVehicles
        return {"vehicles": vehicles}
    finally:
        await client.async_close()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mitsubishi Connect EU."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # NumberSelector liefert float — in int umwandeln
            if CONF_UPDATE_INTERVAL in user_input:
                user_input[CONF_UPDATE_INTERVAL] = int(user_input[CONF_UPDATE_INTERVAL])
            try:
                info = await validate_input(self.hass, user_input)
                vehicles = info.get("vehicles", [])
                title = f"Mitsubishi Connect EU ({user_input[CONF_USERNAME]})"
                if vehicles:
                    first = vehicles[0]
                    nick = first.get("nickName", "")
                    vin = first.get("vin", "")
                    if nick:
                        title = nick
                    elif vin:
                        title = f"Mitsubishi {vin[-6:]}"

                return self.async_create_entry(title=title, data=user_input)

            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoVehicles:
                errors["base"] = "no_vehicles"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Credentials aendern ohne Integration zu loeschen."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            if CONF_UPDATE_INTERVAL in user_input:
                user_input[CONF_UPDATE_INTERVAL] = int(user_input[CONF_UPDATE_INTERVAL])
            try:
                await validate_input(self.hass, user_input)
                self.hass.config_entries.async_update_entry(entry, data=user_input)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoVehicles:
                errors["base"] = "no_vehicles"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): _TEXT,
                    vol.Required(CONF_PASSWORD): _PASSWORD,
                    vol.Required(CONF_PIN, default=entry.data.get(CONF_PIN, "")): _PASSWORD,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                    ): _NUMBER,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options — Credentials und Einstellungen aendern."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if CONF_UPDATE_INTERVAL in user_input:
                user_input[CONF_UPDATE_INTERVAL] = int(user_input[CONF_UPDATE_INTERVAL])
            new_data = {**self._config_entry.data}
            new_data[CONF_USERNAME] = user_input[CONF_USERNAME]
            new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            new_data[CONF_PIN] = user_input[CONF_PIN]
            new_data[CONF_UPDATE_INTERVAL] = user_input[CONF_UPDATE_INTERVAL]

            try:
                await validate_input(self.hass, new_data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoVehicles:
                errors["base"] = "no_vehicles"
            except Exception:
                _LOGGER.exception("Unexpected exception in options flow")
                errors["base"] = "unknown"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )
                return self.async_create_entry(
                    title="",
                    data={CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL]},
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=self._config_entry.data.get(CONF_USERNAME, ""),
                    ): _TEXT,
                    vol.Required(CONF_PASSWORD): _PASSWORD,
                    vol.Required(
                        CONF_PIN,
                        default=self._config_entry.data.get(CONF_PIN, ""),
                    ): _PASSWORD,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_UPDATE_INTERVAL,
                            self._config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                        ),
                    ): _NUMBER,
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class NoVehicles(HomeAssistantError):
    """Error to indicate no vehicles found."""
