"""b11 in echtem HA: Dienst request_status (nur Antwort), Motor-Remote-Schalter deaktiviert."""
from __future__ import annotations

import pytest

from homeassistant.helpers import entity_registry as er

from test_reload import DATA, VIN, FakeClient, _setup, fake_client, needs_wake  # noqa: F401
from custom_components.mitsubishi_outlander_phev_eu.const import DOMAIN


async def test_request_status_service_returns_response(hass, monkeypatch):
    calls = []

    async def req(self, rid):
        calls.append(rid)
        return {"request_id": rid, "status": 1, "request_status_list": [{"requestId": rid, "status": 1}],
                "error": None}
    monkeypatch.setattr(FakeClient, "async_request_status", req, raising=False)
    await _setup(hass)
    assert hass.services.has_service(DOMAIN, "request_status")
    res = await hass.services.async_call(
        DOMAIN, "request_status", {"request_id": "REQ-1"}, blocking=True, return_response=True)
    assert calls == ["REQ-1"]
    assert res["status"] == 1 and res["request_status_list"][0]["requestId"] == "REQ-1"


async def test_request_status_requires_response(hass):
    await _setup(hass)
    from homeassistant.exceptions import ServiceValidationError
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "request_status", {"request_id": "R"}, blocking=True)


async def test_engine_switch_disabled_by_default(hass):
    entry = await _setup(hass)
    reg = er.async_get(hass)
    eid = reg.async_get_entity_id("switch", DOMAIN, f"{VIN}_remote_engine")
    assert eid is not None
    assert reg.async_get(eid).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert eid.endswith("_motor_remote_diagnostics") or eid.endswith("_remote_engine_diagnostics"), eid
    assert reg.async_get_entity_id("switch", DOMAIN, f"{VIN}_climate") is not None
