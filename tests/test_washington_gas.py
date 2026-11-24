"""Tests. All bill data is made up."""

from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import patch
from zoneinfo import ZoneInfo

from opower import MeterType, select_utility
from opower.exceptions import CannotConnect, InvalidAuth, MfaChallenge
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.washington_gas import config_flow, coordinator  # noqa: F401
from custom_components.washington_gas.coordinator import account_slot
from custom_components.washington_gas.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.helpers import entity_registry as er

TZ = ZoneInfo("America/New_York")
BASE = "custom_components.washington_gas"


def d(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def read(start, end, usage, cost):
    return NS(
        start_time=d(start), end_time=d(end), consumption=usage, provided_cost=cost
    )


# Spans both DST changes.
BILLS = [
    read("2025-10-05", "2025-11-04", 20.0, 50.0),
    read("2025-11-04", "2025-12-05", 60.0, 110.0),
    read("2025-12-05", "2026-03-20", 150.0, 260.0),
]
TOTAL_USAGE, TOTAL_COST, DAYS = 230.0, 420.0, 166
ACCOUNT_1 = NS(uuid="uuid-one", meter_type=MeterType.GAS)
ACCOUNT_2 = NS(uuid="uuid-two", meter_type=MeterType.GAS)


class FakeApi:
    def __init__(self):
        self.exc = None
        self.accounts = [ACCOUNT_1]
        self.reads = {"uuid-one": BILLS, "uuid-two": BILLS[:1]}

    async def async_login(self):
        if self.exc:
            raise self.exc

    async def async_get_accounts(self):
        return self.accounts

    async def async_get_cost_reads(self, account, *args):
        return self.reads[account.uuid]


@pytest.fixture(autouse=True)
def _setup(recorder_mock, enable_custom_integrations):
    """Recorder must come before hass."""


@pytest.fixture
def api():
    fake = FakeApi()
    with (
        patch(f"{BASE}.coordinator.create_api", lambda *a: fake),
        patch(f"{BASE}.config_flow.create_api", lambda *a: fake),
    ):
        yield fake


async def setup(hass, version=2):
    entry = MockConfigEntry(
        domain="washington_gas",
        title="Washington Gas",
        version=version,
        unique_id="user@example.com",
        data={"username": "user@example.com", "password": "secret"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def stats(hass, *ids):
    await async_wait_recording_done(hass)
    return await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        d("2025-01-01"),
        None,
        set(ids),
        "hour",
        None,
        {"sum", "change"},
    )


async def test_import_reload_correction_options(hass, api):
    entry = await setup(hass)
    slot = account_slot("uuid-one")
    cost_id, use_id = (
        f"washington_gas:{slot}_cost",
        f"washington_gas:{slot}_consumption",
    )
    data = await stats(hass, cost_id, use_id)
    assert len(data[cost_id]) == DAYS
    assert data[cost_id][-1]["sum"] == pytest.approx(TOTAL_COST)
    assert sum(r["change"] for r in data[cost_id]) == pytest.approx(TOTAL_COST)
    assert data[use_id][-1]["sum"] == pytest.approx(TOTAL_USAGE / 1.04)
    assert hass.states.get("sensor.washington_gas_last_bill_cost").state == "260.0"
    assert hass.states.get("sensor.washington_gas_last_bill_end").state == "2026-03-19"

    await entry.runtime_data.async_refresh()
    await hass.config_entries.async_reload(entry.entry_id)
    data = await stats(hass, cost_id)
    assert len(data[cost_id]) == DAYS
    assert data[cost_id][-1]["sum"] == pytest.approx(TOTAL_COST)

    # The portal drops the oldest bill and corrects another.
    api.reads["uuid-one"] = [read("2025-11-04", "2025-12-05", 60.0, 120.0), BILLS[2]]
    await entry.runtime_data.async_refresh()
    data = await stats(hass, cost_id)
    assert data[cost_id][-1]["sum"] == pytest.approx(TOTAL_COST + 10)

    hass.config_entries.async_update_entry(entry, options={"usage_unit": "CCF"})
    await hass.config_entries.async_reload(entry.entry_id)
    data = await stats(hass, use_id)
    assert data[use_id][-1]["sum"] == pytest.approx(TOTAL_USAGE)
    state = hass.states.get("sensor.washington_gas_last_bill_usage")
    assert state.attributes["unit_of_measurement"] == "CCF"


async def test_upgrade_from_version_1(hass, api, hass_storage):
    """IDs and cached history survive; no second set of statistics appears."""
    entry = MockConfigEntry(
        domain="washington_gas",
        title="Washington Gas",
        version=1,
        unique_id="user@example.com",
        data={"username": "user@example.com", "password": "secret"},
    )
    entry.add_to_hass(hass)
    hass_storage[f"washington_gas.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"washington_gas.{entry.entry_id}",
        "data": [
            {"start": "2025-09-05", "end": "2025-10-05", "therms": 5.0, "cost": 25.0}
        ],
    }
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        "washington_gas",
        f"{entry.entry_id}_last_bill_cost",
        suggested_object_id="my_custom_name",
        config_entry=entry,
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2
    assert hass.states.get(old.entity_id).state == "260.0"
    data = await stats(
        hass, "washington_gas:cost", f"washington_gas:{account_slot('uuid-one')}_cost"
    )
    assert set(data) == {"washington_gas:cost"}
    assert data["washington_gas:cost"][-1]["sum"] == pytest.approx(TOTAL_COST + 25)

    # A second account later gets its own IDs.
    api.accounts = [ACCOUNT_2, ACCOUNT_1]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    data = await stats(
        hass, "washington_gas:cost", f"washington_gas:{account_slot('uuid-two')}_cost"
    )
    assert len(data) == 2
    assert data["washington_gas:cost"][-1]["sum"] == pytest.approx(TOTAL_COST + 25)
    assert len(registry.entities) == 10


async def test_one_bad_account_does_not_block_another(hass, api):
    api.accounts = [ACCOUNT_1, ACCOUNT_2]
    api.reads["uuid-one"] = [read("2025-01-01", "2125-01-01", 1.0, 1.0)]
    entry = await setup(hass)
    assert set(entry.runtime_data.data) == {account_slot("uuid-two")}


@pytest.mark.parametrize(
    "bad",
    [
        {"end_time": d("2126-01-01")},
        {"start_time": d("2025-12-01")},
        {"consumption": float("nan")},
        {"consumption": None},
        {"provided_cost": 1e9},
    ],
)
async def test_bad_data_keeps_history(hass, api, bad):
    entry = await setup(hass)
    api.reads["uuid-one"] = [*BILLS[:-1], NS(**{**vars(BILLS[-1]), **bad})]
    await entry.runtime_data.async_refresh()
    assert not entry.runtime_data.last_update_success
    cost_id = f"washington_gas:{account_slot('uuid-one')}_cost"
    data = await stats(hass, cost_id)
    assert data[cost_id][-1]["sum"] == pytest.approx(TOTAL_COST)
    assert hass.states.get("sensor.washington_gas_last_bill_cost").state == "260.0"


async def test_outage_then_bad_password(hass, api):
    entry = await setup(hass)
    api.exc = CannotConnect("down")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.washington_gas_last_bill_cost").state == "260.0"
    api.exc = InvalidAuth("no")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    api.exc = None
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {"password": "new"}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new"
    await hass.async_block_till_done()


async def test_crash_is_contained(hass, api):
    api.exc = RuntimeError("boom")
    entry = await setup(hass)
    assert entry.state.value == "setup_retry"


@pytest.mark.parametrize(
    ("exc", "accounts", "error"),
    [
        (InvalidAuth("x"), [ACCOUNT_1], "invalid_auth"),
        (MfaChallenge("x", None), [ACCOUNT_1], "mfa_not_supported"),
        (CannotConnect("x"), [ACCOUNT_1], "cannot_connect"),
        (None, [], "no_gas_account"),
    ],
)
async def test_flow(hass, api, exc, accounts, error):
    user = {"username": "User@example.com", "password": "secret"}
    result = await hass.config_entries.flow.async_init(
        "washington_gas", context={"source": "user"}
    )
    api.exc, api.accounts = exc, accounts
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    assert result["errors"] == {"base": error}
    api.exc, api.accounts = None, [ACCOUNT_1]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user)
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    options = await hass.config_entries.options.async_init(result["result"].entry_id)
    assert options["step_id"] == "init"


async def test_diagnostics_have_no_private_data(hass, api):
    entry = await setup(hass)
    text = str(await async_get_config_entry_diagnostics(hass, entry))
    for private in (
        "user@example.com",
        "secret",
        "uuid-one",
        "260",
        "150.0",
        "2025-",
        "2026-",
    ):
        assert private not in text


@pytest.mark.parametrize(
    ("status", "exc"),
    [(204, None), (307, CannotConnect), (401, InvalidAuth)],
)
async def test_login(status, exc):
    class Response:
        async def __aenter__(self):
            self.status = status
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

    class Session:
        def post(self, url, **kwargs):
            assert url.startswith("https://wgl.opower.com/")
            assert kwargs["allow_redirects"] is False
            return Response()

    utility = select_utility("Washington Gas")()
    if exc:
        with pytest.raises(exc):
            await utility.async_login(Session(), "a", "b", {})
    else:
        assert await utility.async_login(Session(), "a", "b", {}) is None


def test_fixture_days():
    assert (date(2026, 3, 20) - date(2025, 10, 5)).days == DAYS
