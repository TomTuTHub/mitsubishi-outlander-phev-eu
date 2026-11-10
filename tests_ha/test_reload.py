"""Optionen speichern -> Reload -> Entry geladen, Entitaeten verfuegbar (echtes HA).

Bug seit 1.0.7: der Update-Listener rief async_setup_entry direkt auf, der
Coordinator hatte keinen Config-Entry -> ConfigEntryError bei jedem Speichern.
Fake-Client statt Netz.
"""
from __future__ import annotations

import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.mitsubishi_outlander_phev_eu.api import VehicleState
from custom_components.mitsubishi_outlander_phev_eu.const import (
    CONF_PASSWORD, CONF_PIN, CONF_UPDATE_INTERVAL, CONF_USERNAME, DOMAIN,
)

PKG = "custom_components.mitsubishi_outlander_phev_eu"
VIN = "TESTVIN0000000001"


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, username, password, pin=""):
        self.username, self.password, self.pin = username, password, pin
        self.logins = 0
        self.closed = False
        FakeClient.instances.append(self)

    async def async_login(self):
        self.logins += 1
        return True

    async def async_get_vehicles(self): return [{"vin": VIN, "nickName": "Testauto"}]
    async def async_close(self): self.closed = True
    async def async_refresh_status(self, vin): return True

    async def async_get_vehicle_status(self, vin):
        return VehicleState(vin=vin, battery_level=80, odometer=1000.0)


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(f"{PKG}.MitsubishiEUClient", FakeClient)
    monkeypatch.setattr(f"{PKG}.config_flow.MitsubishiEUClient", FakeClient)

    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(f"{PKG}.asyncio.sleep", no_sleep)
    yield


DATA = {CONF_USERNAME: "u@example.org", CONF_PASSWORD: "pw", CONF_PIN: "1234",
        CONF_UPDATE_INTERVAL: 15}


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, title="Testauto")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _assert_loaded_and_available(hass, entry):
    assert entry.state is ConfigEntryState.LOADED, entry.state
    reg = er.async_get(hass)
    states = {}
    for e in er.async_entries_for_config_entry(reg, entry.entry_id):
        if e.disabled_by:
            continue
        st = hass.states.get(e.entity_id)
        states[e.entity_id] = st.state if st else None
    assert states, "keine Entitaeten"
    bad = {k: v for k, v in states.items() if v in (None, "unavailable")}
    assert not bad, bad
    assert entry.entry_id in hass.data[DOMAIN]


def _no_errors(caplog):
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errs, [r.getMessage() for r in errs]


async def _save_options(hass, entry, interval):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    res = await hass.config_entries.options.async_configure(flow["flow_id"], {
        CONF_USERNAME: DATA[CONF_USERNAME], CONF_PASSWORD: DATA[CONF_PASSWORD],
        CONF_PIN: DATA[CONF_PIN], CONF_UPDATE_INTERVAL: interval})
    await hass.async_block_till_done()
    return res


async def test_save_options_and_back_keeps_entry_loaded(hass, caplog):
    entry = await _setup(hass)
    _assert_loaded_and_available(hass, entry)
    res = await _save_options(hass, entry, 30)
    assert res["type"] == "create_entry"
    assert entry.options[CONF_UPDATE_INTERVAL] == 30
    _assert_loaded_and_available(hass, entry)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]
    assert coord.config_entry is entry
    assert coord.update_interval.total_seconds() == 30 * 60
    await _save_options(hass, entry, 15)
    _assert_loaded_and_available(hass, entry)
    # Unload ueber den HA-Lebenszyklus muss sauber gehen (vorher KeyError)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    _no_errors(caplog)


async def test_update_listener_reloads_via_ha(hass, caplog):
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_UPDATE_INTERVAL: 20})
    await hass.async_block_till_done()
    _assert_loaded_and_available(hass, entry)
    assert hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN].update_interval.total_seconds() == 20 * 60
    assert await hass.config_entries.async_unload(entry.entry_id)
    _no_errors(caplog)


async def test_reconfigure_reloads_once(hass, caplog):
    entry = await _setup(hass)
    setups_before = len(FakeClient.instances)
    flow = await entry.start_reconfigure_flow(hass)
    res = await hass.config_entries.flow.async_configure(flow["flow_id"], {
        **DATA, CONF_PIN: "9999"})
    await hass.async_block_till_done()
    assert res["type"] == "abort" and res["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PIN] == "9999"
    _assert_loaded_and_available(hass, entry)
    # 1 Client fuer die Validierung + 1 fuer genau einen Reload
    assert len(FakeClient.instances) - setups_before == 2
    _no_errors(caplog)


async def test_unload_twice_no_exception(hass, caplog):
    entry = await _setup(hass)
    from custom_components.mitsubishi_outlander_phev_eu import async_unload_entry
    assert await async_unload_entry(hass, entry)
    assert await async_unload_entry(hass, entry)
    _no_errors(caplog)
