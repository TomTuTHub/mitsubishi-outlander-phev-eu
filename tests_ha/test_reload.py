"""Options-Aenderung -> Reload -> Entry geladen, Entitaeten verfuegbar (echtes HA).

Fake-Client statt Netz. `needs_wake=True` bildet einen Server nach, der ohne
refreshVSR keine Daten liefert (Verdacht Japan nach b4-Bericht 29.10.).
"""
from __future__ import annotations

import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.mitsubishi_outlander_phev_eu.api import VehicleState
from custom_components.mitsubishi_outlander_phev_eu.const import (
    CONF_PASSWORD, CONF_PIN, CONF_REGION, CONF_UPDATE_INTERVAL, CONF_USERNAME,
    CONF_WAKE_ON_POLL, DOMAIN,
)

PKG = "custom_components.mitsubishi_outlander_phev_eu"
VIN = "TESTVIN0000000001"


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, data, needs_wake=False):
        self.data = dict(data)
        self.needs_wake = needs_wake
        self.woken = False
        self.refresh_calls = 0
        self.closed = False
        FakeClient.instances.append(self)

    async def async_login(self): return True
    async def async_get_vehicles(self): return [{"vin": VIN, "nickName": "Testauto"}]
    async def async_close(self): self.closed = True

    async def async_refresh_status(self, vin):
        self.refresh_calls += 1
        self.woken = True
        return True

    async def async_get_vehicle_status(self, vin):
        if self.needs_wake and not self.woken:
            return VehicleState(vin=vin)          # Server hat nichts
        return VehicleState(vin=vin, battery_level=80, odometer=1000.0)


@pytest.fixture
def needs_wake():
    return {"value": False}


@pytest.fixture(autouse=True)
def fake_client(monkeypatch, needs_wake):
    FakeClient.instances.clear()

    def factory(data, **kw):
        return FakeClient(data, needs_wake=needs_wake["value"])

    monkeypatch.setattr(f"{PKG}.create_client", factory)
    monkeypatch.setattr(f"{PKG}.config_flow.create_client", factory)

    async def no_sleep(*a, **k):
        return None
    monkeypatch.setattr(f"{PKG}.asyncio.sleep", no_sleep)
    yield


DATA = {CONF_REGION: "jp_1", CONF_USERNAME: "u@example.org", CONF_PASSWORD: "pw",
        CONF_PIN: "1234", CONF_UPDATE_INTERVAL: 15}


async def _setup(hass, options=None, data=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data or DATA, options=options or {},
                            title="Testauto")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _states(hass, entry):
    reg = er.async_get(hass)
    out = {}
    for e in er.async_entries_for_config_entry(reg, entry.entry_id):
        if e.disabled_by:
            continue
        st = hass.states.get(e.entity_id)
        out[e.entity_id] = st.state if st else None
    return out


def _assert_loaded_and_available(hass, entry):
    assert entry.state is ConfigEntryState.LOADED, entry.state
    states = _states(hass, entry)
    assert states, "keine Entitaeten"
    bad = {k: v for k, v in states.items() if v in (None, "unavailable")}
    assert not bad, bad
    assert entry.entry_id in hass.data[DOMAIN]


def _no_errors(caplog):
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errs, [r.getMessage() for r in errs]


async def _options(hass, entry, **changes):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    user_input = {CONF_USERNAME: entry.data[CONF_USERNAME],
                  CONF_UPDATE_INTERVAL: 15,
                  CONF_WAKE_ON_POLL: entry.options.get(CONF_WAKE_ON_POLL, True)}
    user_input.update(changes)
    res = await hass.config_entries.options.async_configure(flow["flow_id"], user_input)
    await hass.async_block_till_done()
    return res


@pytest.mark.parametrize("wake", [False, True])
async def test_options_change_reload_keeps_entry_loaded(hass, caplog, wake):
    entry = await _setup(hass, options={CONF_WAKE_ON_POLL: not wake})
    _assert_loaded_and_available(hass, entry)
    res = await _options(hass, entry, **{CONF_WAKE_ON_POLL: wake})
    assert res["type"] == "create_entry"
    assert entry.options[CONF_WAKE_ON_POLL] is wake
    _assert_loaded_and_available(hass, entry)
    # Unload ueber den HA-Lebenszyklus muss sauber gehen (b4: KeyError Z.148)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    _no_errors(caplog)


async def test_wake_off_toggle_and_back_on(hass, caplog):
    entry = await _setup(hass)
    await _options(hass, entry, **{CONF_WAKE_ON_POLL: False})
    _assert_loaded_and_available(hass, entry)
    await _options(hass, entry, **{CONF_WAKE_ON_POLL: True})
    _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_options_update_listener_directly(hass, caplog):
    """Update-Listener wie bei Options-Speichern ohne Flow (nur options aendern)."""
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_WAKE_ON_POLL: False})
    await hass.async_block_till_done()
    _assert_loaded_and_available(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    _no_errors(caplog)


async def test_data_and_options_change_together(hass, caplog):
    """Options-Flow aendert data (Zugangsdaten) UND options -> zwei Listener-Aufrufe."""
    entry = await _setup(hass)
    await _options(hass, entry, **{CONF_UPDATE_INTERVAL: 30, CONF_WAKE_ON_POLL: False,
                                   CONF_PIN: "9999"})
    _assert_loaded_and_available(hass, entry)
    assert entry.data[CONF_PIN] == "9999"
    assert await hass.config_entries.async_unload(entry.entry_id)
    _no_errors(caplog)


async def test_region_change_via_reconfigure(hass, caplog):
    entry = await _setup(hass, data={**DATA, CONF_REGION: "eu"})
    flow = await entry.start_reconfigure_flow(hass)
    res = await hass.config_entries.flow.async_configure(flow["flow_id"], {
        CONF_REGION: "jp_1", CONF_USERNAME: DATA[CONF_USERNAME],
        CONF_UPDATE_INTERVAL: 15})
    await hass.async_block_till_done()
    assert res["type"] == "abort" and res["reason"] == "reconfigure_successful"
    assert entry.data[CONF_REGION] == "jp_1"
    assert entry.data[CONF_PASSWORD] == DATA[CONF_PASSWORD]   # leer = unveraendert
    assert entry.data[CONF_PIN] == DATA[CONF_PIN]
    _assert_loaded_and_available(hass, entry)
    assert FakeClient.instances[-1].data[CONF_REGION] == "jp_1"
    assert await hass.config_entries.async_unload(entry.entry_id)
    _no_errors(caplog)


async def test_restart_with_wake_off_and_silent_server(hass, caplog, needs_wake):
    """Neustart mit wake_on_poll=False, Server liefert ohne refreshVSR nichts.

    b4: UpdateFailed im ersten Refresh -> ConfigEntryNotReady -> SETUP_RETRY
    endlos, alle Entitaeten nicht verfuegbar (auch der Button)."""
    needs_wake["value"] = True
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={CONF_WAKE_ON_POLL: False})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    _assert_loaded_and_available(hass, entry)
    client = FakeClient.instances[-1]
    assert client.refresh_calls == 1     # genau einmal beim Start geweckt
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]
    await coord.async_refresh()          # normale Abfrage: weckt nicht mehr
    assert client.refresh_calls == 1
    _assert_loaded_and_available(hass, entry)


async def test_restart_wake_off_server_never_answers_still_loaded(hass, needs_wake, monkeypatch):
    """Auch wenn selbst das Aufwecken nichts bringt: Entry geladen, Button nutzbar."""
    needs_wake["value"] = True

    async def refresh_no_effect(self, vin):
        self.refresh_calls += 1
        return True
    monkeypatch.setattr(FakeClient, "async_refresh_status", refresh_no_effect)
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={CONF_WAKE_ON_POLL: False})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    button = hass.states.get("button.testauto_status_aktualisieren") or next(
        hass.states.get(e.entity_id) for e in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id) if e.unique_id.endswith("_refresh"))
    assert button.state != "unavailable"


async def test_unload_twice_no_exception(hass, caplog):
    entry = await _setup(hass)
    from custom_components.mitsubishi_outlander_phev_eu import async_unload_entry
    assert await async_unload_entry(hass, entry)
    assert await async_unload_entry(hass, entry)   # zweites Mal: kein KeyError
    _no_errors(caplog)


async def test_options_form_has_no_secret_defaults(hass):
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    for key in flow["data_schema"].schema:
        if str(key) in (CONF_PIN, CONF_PASSWORD):
            assert key.default is __import__("voluptuous").UNDEFINED, str(key)
    flow = await entry.start_reconfigure_flow(hass)
    for key in flow["data_schema"].schema:
        if str(key) in (CONF_PIN, CONF_PASSWORD):
            assert key.default is __import__("voluptuous").UNDEFINED, str(key)


async def test_empty_secret_fields_keep_old_values(hass):
    entry = await _setup(hass)
    await _options(hass, entry, **{CONF_PIN: "", CONF_PASSWORD: ""})
    assert entry.data[CONF_PIN] == DATA[CONF_PIN]
    assert entry.data[CONF_PASSWORD] == DATA[CONF_PASSWORD]
