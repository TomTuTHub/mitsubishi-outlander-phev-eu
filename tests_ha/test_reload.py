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
from custom_components.mitsubishi_outlander_phev_eu.session import SessionMonitor
from custom_components.mitsubishi_outlander_phev_eu.const import (
    CONF_PASSWORD, CONF_PIN, CONF_UPDATE_INTERVAL, CONF_USERNAME, DOMAIN,
)

PKG = "custom_components.mitsubishi_outlander_phev_eu"
VIN = "TESTVIN0000000001"


class FakeClient:
    instances: list["FakeClient"] = []
    role = "setup"                       # "setup" (Reload) oder "validate" (Pruef-Login)

    def __init__(self, username, password, pin="", session=None):
        self.username, self.password, self.pin = username, password, pin
        self.session = session if session is not None else SessionMonitor()
        self.last_status_valid = 1
        self.logins = 0
        self.refresh_calls = 0
        self.closed = False
        FakeClient.instances.append(self)

    def begin_cycle(self):
        pass

    async def async_login(self):
        self.logins += 1
        return True

    async def async_get_vehicles(self): return [{"vin": VIN, "nickName": "Testauto"}]
    async def async_close(self): self.closed = True
    async def async_refresh_status(self, vin):
        self.refresh_calls += 1
        return True

    async def async_get_vehicle_status(self, vin):
        return VehicleState(vin=vin, battery_level=80, odometer=1000.0)


class ValidateClient(FakeClient):
    role = "validate"


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(f"{PKG}.MitsubishiEUClient", FakeClient)
    monkeypatch.setattr(f"{PKG}.config_flow.MitsubishiEUClient", ValidateClient)

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


# ---------------------------------------------------------------------------
# 1.0.10: Optionen speichern = genau 1 Reload, Pruef-Login nur bei neuen Zugangsdaten
# ---------------------------------------------------------------------------

def _count(before):
    new = FakeClient.instances[before:]
    return {
        "validate": sum(1 for c in new if c.role == "validate"),
        "reloads": sum(1 for c in new if c.role == "setup"),
        "logins": sum(c.logins for c in new),
        "wakes": sum(c.refresh_calls for c in new),
    }


async def _options(hass, entry, **user_input):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    data = {CONF_USERNAME: entry.data[CONF_USERNAME], CONF_UPDATE_INTERVAL: 15}
    data.update(user_input)
    res = await hass.config_entries.options.async_configure(flow["flow_id"], data)
    await hass.async_block_till_done()
    return res


async def test_save_interval_unchanged_credentials_one_reload_no_check_login(hass, caplog):
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    res = await _options(hass, entry, **{CONF_UPDATE_INTERVAL: 30})
    assert res["type"] == "create_entry"
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"], c["wakes"]) == (0, 1, 1, 1), c
    assert entry.options[CONF_UPDATE_INTERVAL] == 30
    assert entry.data[CONF_PASSWORD] == DATA[CONF_PASSWORD]
    assert entry.data[CONF_PIN] == DATA[CONF_PIN]
    _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_save_and_back_each_one_reload(hass, caplog):
    entry = await _setup(hass)
    for interval in (30, 15):
        before = len(FakeClient.instances)
        await _options(hass, entry, **{CONF_UPDATE_INTERVAL: interval})
        c = _count(before)
        assert (c["validate"], c["reloads"], c["logins"]) == (0, 1, 1), c
        _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_same_password_typed_again_counts_as_unchanged(hass):
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    await _options(hass, entry, **{CONF_PASSWORD: DATA[CONF_PASSWORD], CONF_PIN: DATA[CONF_PIN],
                                   CONF_UPDATE_INTERVAL: 20})
    c = _count(before)
    assert (c["validate"], c["reloads"]) == (0, 1), c


@pytest.mark.parametrize("change", [
    {CONF_PASSWORD: "neu"}, {CONF_PIN: "4321"}, {CONF_USERNAME: "other@example.org"}])
async def test_changed_credentials_check_login_then_one_reload(hass, caplog, change):
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    await _options(hass, entry, **{CONF_UPDATE_INTERVAL: 30, **change})
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"]) == (1, 1, 2), c
    for k, v in change.items():
        assert entry.data[k] == v
    assert entry.options[CONF_UPDATE_INTERVAL] == 30
    _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_save_without_any_change_does_not_reload(hass):
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_UPDATE_INTERVAL: 15})
    await hass.async_block_till_done()
    before = len(FakeClient.instances)
    res = await _options(hass, entry)
    assert res["type"] == "create_entry"
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"]) == (0, 0, 0), c
    _assert_loaded_and_available(hass, entry)


async def test_invalid_new_password_no_reload(hass, monkeypatch):
    entry = await _setup(hass)

    async def bad_login(self):
        self.logins += 1
        return False
    monkeypatch.setattr(ValidateClient, "async_login", bad_login)
    before = len(FakeClient.instances)
    res = await _options(hass, entry, **{CONF_PASSWORD: "falsch"})
    assert res["type"] == "form" and res["errors"]["base"] == "invalid_auth"
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"]) == (1, 0, 1), c
    assert entry.data[CONF_PASSWORD] == DATA[CONF_PASSWORD]


async def test_options_form_has_no_secret_defaults(hass):
    entry = await _setup(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    for key in flow["data_schema"].schema:
        if str(key) in (CONF_PIN, CONF_PASSWORD):
            assert key.default is __import__("voluptuous").UNDEFINED, str(key)


# ---------------------------------------------------------------------------
# 1.0.10: ForceLogout (600002) -> UpdateFailed sofort, kein 90-s-Polling
# ---------------------------------------------------------------------------

@pytest.fixture
def sleeps(monkeypatch):
    calls = []

    async def counting_sleep(seconds, *a, **k):
        calls.append(seconds)
    monkeypatch.setattr(f"{PKG}.asyncio.sleep", counting_sleep)
    return calls


@pytest.mark.parametrize("where", ["refresh", "status"])
async def test_force_logout_in_poll_fails_fast(hass, monkeypatch, sleeps, where):
    from custom_components.mitsubishi_outlander_phev_eu.api import ForceLogoutError
    entry = await _setup(hass)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]

    async def boom(self, vin):
        raise ForceLogoutError("600002")
    target = "async_refresh_status" if where == "refresh" else "async_get_vehicle_status"
    monkeypatch.setattr(FakeClient, target, boom)
    sleeps.clear()
    await coord.async_refresh()
    assert coord.last_update_success is False
    assert sum(sleeps) <= 15, sleeps


async def test_force_logout_at_setup_is_not_ready(hass, monkeypatch):
    from custom_components.mitsubishi_outlander_phev_eu.api import ForceLogoutError

    async def boom(self):
        raise ForceLogoutError("600002")
    monkeypatch.setattr(FakeClient, "async_get_vehicles", boom)
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, title="Testauto")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert FakeClient.instances[-1].closed


async def test_coordinator_update_starts_new_cycle(hass):
    entry = await _setup(hass)
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    calls = []
    client.begin_cycle = lambda: calls.append(1)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]
    await coord.async_refresh()
    assert calls == [1]


# ---------------------------------------------------------------------------
# 1.0.11: Sitzungsverlust -> Diagnose-Sensor "Verbindung" zeigt den Grund
# ---------------------------------------------------------------------------

def _conn_state(hass, entry):
    reg = er.async_get(hass)
    ent = reg.async_get_entity_id("sensor", DOMAIN, f"{VIN}_connection")
    assert ent, "Diagnose-Sensor fehlt"
    return reg.async_get(ent), hass.states.get(ent)


async def test_connection_sensor_ok_and_diagnostic(hass):
    entry = await _setup(hass)
    reg_entry, st = _conn_state(hass, entry)
    assert reg_entry.entity_category.value == "diagnostic"
    assert st.state == "ok"
    assert st.attributes["relogin_count"] == 0
    assert st.attributes["last_relogin"] is None
    assert set(st.attributes["options"]) == {
        "ok", "session_lost", "waiting_for_relogin", "vehicle_not_responding",
        "login_failed", "network_error"}


async def test_vehicle_not_responding_shows_reason_and_keeps_sensor_available(hass, monkeypatch, caplog):
    entry = await _setup(hass)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]

    orig = FakeClient.async_get_vehicle_status

    async def empty(self, vin):
        self.last_status_valid = 3          # Server antwortet, Fahrzeug nicht
        return VehicleState(vin=vin)
    monkeypatch.setattr(FakeClient, "async_get_vehicle_status", empty)
    caplog.set_level(logging.WARNING)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.last_update_success is False
    _, st = _conn_state(hass, entry)
    assert st.state == "vehicle_not_responding"      # nicht "unavailable"
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(m.startswith("Fahrzeug antwortet nicht (Sitzung ok)") for m in msgs), msgs
    # Fahrzeug meldet sich wieder -> ok
    monkeypatch.setattr(FakeClient, "async_get_vehicle_status", orig)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert _conn_state(hass, entry)[1].state == "ok"


async def test_session_lost_shows_waiting_state_with_attributes(hass, monkeypatch):
    from custom_components.mitsubishi_outlander_phev_eu.api import SessionLostError
    from custom_components.mitsubishi_outlander_phev_eu import session as sess
    entry = await _setup(hass)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]
    mon = hass.data[DOMAIN][entry.entry_id]["client"].session

    async def lost(self, vin):
        mon.start_relogin("errorCode 600002")
        mon.set_state(sess.STATE_WAITING_RELOGIN, "errorCode 600002")
        raise SessionLostError("Sitzung verloren (errorCode 600002); naechster Neu-Login fruehestens 12:34")
    monkeypatch.setattr(FakeClient, "async_refresh_status", lost)
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.last_update_success is False
    _, st = _conn_state(hass, entry)
    assert st.state == "waiting_for_relogin"
    assert st.attributes["relogin_count"] == 1
    assert st.attributes["last_relogin"] and st.attributes["next_possible_relogin"]
    assert st.attributes["reason"] == "errorCode 600002"


async def test_rejected_credentials_in_poll_raise_auth_failed(hass, monkeypatch):
    from homeassistant.exceptions import ConfigEntryAuthFailed
    from custom_components.mitsubishi_outlander_phev_eu.api import SessionLostError
    entry = await _setup(hass)
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]

    async def rejected(self, vin):
        raise SessionLostError("Neu-Login fehlgeschlagen", auth_rejected=True)
    monkeypatch.setattr(FakeClient, "async_refresh_status", rejected)
    with pytest.raises(ConfigEntryAuthFailed):
        await coord.update_method()


async def test_backoff_monitor_survives_reload(hass):
    entry = await _setup(hass)
    mon = hass.data[DOMAIN][entry.entry_id]["client"].session
    mon.start_relogin("errorCode 600002")
    await _save_options(hass, entry, 30)
    mon2 = hass.data[DOMAIN][entry.entry_id]["client"].session
    assert mon2 is mon and mon2.relogin_count == 1 and not mon2.can_relogin()
