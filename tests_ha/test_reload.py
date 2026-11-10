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

    def __init__(self, data, needs_wake=False, role="setup"):
        self.data = dict(data)
        self.needs_wake = needs_wake
        self.role = role                  # "setup" (Reload) oder "validate" (Pruef-Login)
        self.woken = False
        self.refresh_calls = 0
        self.logins = 0
        self.closed = False
        FakeClient.instances.append(self)

    async def async_login(self):
        self.logins += 1
        return True
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

    def flow_factory(data, **kw):
        return FakeClient(data, needs_wake=needs_wake["value"], role="validate")

    monkeypatch.setattr(f"{PKG}.create_client", factory)
    monkeypatch.setattr(f"{PKG}.config_flow.create_client", flow_factory)

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
    """Options-Flow aendert data (PIN) UND options -> trotzdem nur EIN Reload (bis b6: 2)."""
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    await _options(hass, entry, **{CONF_UPDATE_INTERVAL: 30, CONF_WAKE_ON_POLL: False,
                                   CONF_PIN: "9999"})
    _assert_loaded_and_available(hass, entry)
    assert entry.data[CONF_PIN] == "9999"
    assert entry.options[CONF_UPDATE_INTERVAL] == 30
    assert entry.options[CONF_WAKE_ON_POLL] is False
    new = FakeClient.instances[before:]
    assert [c.role for c in new] == ["validate", "setup"]   # 1 Pruef-Login + 1 Reload
    assert sum(c.logins for c in new) == 2
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


# ---------------------------------------------------------------------------
# b7: Options-Speichern = genau 1 Reload, Pruef-Login nur bei neuen Zugangsdaten
# ---------------------------------------------------------------------------

def _count(before):
    new = FakeClient.instances[before:]
    return {
        "validate": sum(1 for c in new if c.role == "validate"),
        "reloads": sum(1 for c in new if c.role == "setup"),
        "logins": sum(c.logins for c in new),
        "wakes": sum(c.refresh_calls for c in new),
    }


@pytest.mark.parametrize("wake", [False, True])
async def test_save_options_unchanged_credentials_one_reload_no_check_login(hass, caplog, wake):
    """Nur eine Option aendert sich, Passwort/PIN leer: kein Pruef-Login, 1 Reload, 1 Login."""
    entry = await _setup(hass, options={CONF_WAKE_ON_POLL: not wake})
    before = len(FakeClient.instances)
    res = await _options(hass, entry, **{CONF_WAKE_ON_POLL: wake, CONF_PASSWORD: "", CONF_PIN: ""})
    assert res["type"] == "create_entry"
    c = _count(before)
    assert c["validate"] == 0
    assert c["reloads"] == 1
    assert c["logins"] == 1
    assert c["wakes"] == (1 if wake else 0)     # hoechstens einmal geweckt
    assert entry.options[CONF_WAKE_ON_POLL] is wake
    _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_save_options_and_back_each_one_reload(hass, caplog):
    entry = await _setup(hass)
    for value in (False, True):
        before = len(FakeClient.instances)
        await _options(hass, entry, **{CONF_WAKE_ON_POLL: value})
        c = _count(before)
        assert (c["validate"], c["reloads"], c["logins"]) == (0, 1, 1), c
        _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_save_interval_only_one_reload(hass, caplog):
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    await _options(hass, entry, **{CONF_UPDATE_INTERVAL: 45})
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"]) == (0, 1, 1), c
    assert entry.options[CONF_UPDATE_INTERVAL] == 45
    assert entry.data[CONF_UPDATE_INTERVAL] == 45
    coord = hass.data[DOMAIN][entry.entry_id]["coordinators"][VIN]
    assert coord.update_interval.total_seconds() == 45 * 60
    _no_errors(caplog)


async def test_same_password_typed_again_counts_as_unchanged(hass):
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    await _options(hass, entry, **{CONF_PASSWORD: DATA[CONF_PASSWORD], CONF_PIN: DATA[CONF_PIN],
                                   CONF_WAKE_ON_POLL: False})
    c = _count(before)
    assert (c["validate"], c["reloads"]) == (0, 1), c


@pytest.mark.parametrize("change", [
    {CONF_PASSWORD: "neu"}, {CONF_PIN: "4321"}, {CONF_USERNAME: "other@example.org"}])
async def test_changed_credentials_check_login_then_one_reload(hass, caplog, change):
    entry = await _setup(hass)
    before = len(FakeClient.instances)
    await _options(hass, entry, **change)
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"]) == (1, 1, 2), c
    for k, v in change.items():
        assert entry.data[k] == v
    assert FakeClient.instances[-1].data[next(iter(change))] == next(iter(change.values()))
    _assert_loaded_and_available(hass, entry)
    _no_errors(caplog)


async def test_save_without_any_change_does_not_reload(hass):
    entry = await _setup(hass, options={CONF_WAKE_ON_POLL: True, CONF_UPDATE_INTERVAL: 15})
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
        return self.role != "validate"
    monkeypatch.setattr(FakeClient, "async_login", bad_login)
    before = len(FakeClient.instances)
    res = await _options(hass, entry, **{CONF_PASSWORD: "falsch"})
    assert res["type"] == "form" and res["errors"]["base"] == "invalid_auth"
    c = _count(before)
    assert (c["validate"], c["reloads"], c["logins"]) == (1, 0, 1), c
    assert entry.data[CONF_PASSWORD] == DATA[CONF_PASSWORD]


# ---------------------------------------------------------------------------
# b7: ForceLogout (600002) -> UpdateFailed sofort, kein 90-s-Polling
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
    client = hass.data[DOMAIN][entry.entry_id]["client"]

    async def boom(self, vin):
        raise ForceLogoutError("600002")
    target = "async_refresh_status" if where == "refresh" else "async_get_vehicle_status"
    monkeypatch.setattr(FakeClient, target, boom)
    sleeps.clear()
    await coord.async_refresh()
    assert coord.last_update_success is False
    # refreshVSR scheitert: gar nicht gewartet; Status scheitert: nur die ersten 15 s
    assert sum(sleeps) <= 15, sleeps
    assert client.logins == 1      # Neu-Login macht der echte Client, nicht der Coordinator


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
