"""Dienste der Integration (b11)."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_REQUEST_STATUS = "request_status"
ATTR_REQUEST_ID = "request_id"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_VIN = "vin"

REQUEST_STATUS_SCHEMA = vol.Schema({
    vol.Required(ATTR_REQUEST_ID): cv.string,
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    vol.Optional(ATTR_VIN): cv.string,
})


def _find_client(hass: HomeAssistant, entry_id: str | None, vin: str | None):
    loaded = {k: v for k, v in (hass.data.get(DOMAIN) or {}).items()
              if isinstance(v, dict) and "client" in v}
    if entry_id:
        data = loaded.get(entry_id)
        if data is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
        return data["client"]
    if vin:
        for data in loaded.values():
            if vin in (data.get("coordinators") or {}):
                return data["client"]
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    if len(loaded) == 1:
        return next(iter(loaded.values()))["client"]
    if not loaded:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_ambiguous")


async def _async_request_status(call: ServiceCall) -> ServiceResponse:
    """Genau ein getBatchRequestStatus, kein Login, kein Wecken, kein Befehl."""
    client = _find_client(call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID), call.data.get(ATTR_VIN))
    return await client.async_request_status(call.data[ATTR_REQUEST_ID])


def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REQUEST_STATUS):
        return
    hass.services.async_register(
        DOMAIN, SERVICE_REQUEST_STATUS, _async_request_status,
        schema=REQUEST_STATUS_SCHEMA, supports_response=SupportsResponse.ONLY,
    )
