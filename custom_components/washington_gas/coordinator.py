"""Fetch Washington Gas bills and import them as statistics."""

import asyncio
from datetime import timedelta
import hashlib
import logging

import aiohttp
from opower import Account, AggregateType, MeterType, Opower, create_cookie_jar
from opower.exceptions import ApiException, CannotConnect, InvalidAuth, MfaChallenge

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .bills import Bill, check, daily_rows, merge
from .const import (
    CONF_LEGACY,
    CONF_LEGACY_ACCOUNT,
    CONF_THERMS_PER_CCF,
    CONF_USAGE_UNIT,
    DEFAULT_THERMS_PER_CCF,
    DEFAULT_USAGE_UNIT,
    DOMAIN,
    UNIT_THERM,
)
from .store import LEGACY_KEY, BillStore
from .utility import UTILITY_NAME

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 60

type WashingtonGasConfigEntry = ConfigEntry[WashingtonGasCoordinator]


def create_api(hass: HomeAssistant, username: str, password: str) -> Opower:
    """Create the API client with its own cookie jar."""
    session = async_create_clientsession(hass, cookie_jar=create_cookie_jar())
    return Opower(session, UTILITY_NAME, username, password)


async def async_gas_accounts(api: Opower) -> list[Account]:
    """Return the gas accounts; call after login."""
    return [a for a in await api.async_get_accounts() if a.meter_type is MeterType.GAS]


def account_slot(account_uuid: str) -> str:
    """Return a stable key that does not reveal the account."""
    return hashlib.sha256(account_uuid.encode()).hexdigest()[:8]


class WashingtonGasCoordinator(DataUpdateCoordinator[dict[str, list[Bill]]]):
    """Poll bills once a day. Data maps an account slot to its bills."""

    config_entry: WashingtonGasConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WashingtonGasConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Washington Gas",
            update_interval=timedelta(days=1),
        )
        self._store = BillStore(hass, entry.entry_id)
        self._stored: dict[str, list[Bill]] | None = None
        self._imported: dict[str, list[Bill]] = {}

    async def _async_update_data(self) -> dict[str, list[Bill]]:
        """Fetch, check, save and import bills."""
        data = self.config_entry.data
        api = create_api(self.hass, data[CONF_USERNAME], data[CONF_PASSWORD])
        fetched: dict[str, list[Bill] | None] = {}
        try:
            async with asyncio.timeout(TIMEOUT):
                await api.async_login()
                accounts = await async_gas_accounts(api)
                if not accounts:
                    raise UpdateFailed("No gas account found")
                for account in accounts:
                    slot = self._slot(account, len(accounts))
                    fetched[slot] = await self._fetch(api, account)
        except (InvalidAuth, MfaChallenge) as err:
            raise ConfigEntryAuthFailed("Washington Gas sign-in rejected") from err
        except (ApiException, CannotConnect, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(
                f"Washington Gas unavailable: {type(err).__name__}"
            ) from err

        if self._stored is None:
            self._stored = await self._store.async_load_bills()
        if all(bills is None for bills in fetched.values()):
            raise UpdateFailed("No account returned usable bills")

        result = dict(self._stored)
        for slot, bills in fetched.items():
            if merged := merge(result.get(slot, []), bills or []):
                result[slot] = merged
        if not result:
            raise UpdateFailed("Washington Gas returned no bills")
        if result != self._stored:
            await self._store.async_save_bills(result)
            self._stored = result
        for slot, bills in result.items():
            if self._imported.get(slot) != bills:
                await self._import(slot, bills)
                self._imported[slot] = bills
        return result

    def _slot(self, account: Account, count: int) -> str:
        """Return the account's slot. Version 1 entries keep their original IDs."""
        data = self.config_entry.data
        if data.get(CONF_LEGACY):
            pinned = data.get(CONF_LEGACY_ACCOUNT)
            slot = account_slot(account.uuid)
            if pinned is None and count == 1:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data={**data, CONF_LEGACY_ACCOUNT: slot}
                )
                pinned = slot
            if pinned is None:
                raise UpdateFailed(
                    "Several accounts found before the original one was identified"
                )
            if slot == pinned:
                return LEGACY_KEY
        return account_slot(account.uuid)

    async def _fetch(self, api: Opower, account: Account) -> list[Bill] | None:
        """Return the account's bills, or None if the data is implausible."""
        reads = await api.async_get_cost_reads(account, AggregateType.BILL)
        try:
            bills = [
                Bill(
                    r.start_time.date(),
                    r.end_time.date(),
                    r.consumption,
                    r.provided_cost,
                )
                for r in reads
            ]
            check(bills)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Ignoring implausible Washington Gas data: %s", err)
            return None
        return bills

    async def _import(self, slot: str, bills: list[Bill]) -> None:
        """Write daily rows; existing rows at the same time are overwritten."""
        tz = await dt_util.async_get_time_zone("America/New_York")
        options = self.config_entry.options
        divisor = (
            options.get(CONF_THERMS_PER_CCF, DEFAULT_THERMS_PER_CCF)
            if options.get(CONF_USAGE_UNIT, DEFAULT_USAGE_UNIT) == UNIT_THERM
            else 1.0
        )
        prefix = "" if slot == LEGACY_KEY else f"{slot}_"
        label = "" if slot == LEGACY_KEY else f" {slot}"
        rows = daily_rows(bills, tz)
        for key, unit_class, unit, data in (
            (
                "consumption",
                VolumeConverter.UNIT_CLASS,
                UnitOfVolume.CENTUM_CUBIC_FEET,
                [
                    StatisticData(start=t, state=u / divisor, sum=us / divisor)
                    for t, u, us, _, _ in rows
                ],
            ),
            (
                "cost",
                None,
                None,
                [StatisticData(start=t, state=c, sum=cs) for t, _, _, c, cs in rows],
            ),
        ):
            async_add_external_statistics(
                self.hass,
                StatisticMetaData(
                    mean_type=StatisticMeanType.NONE,
                    has_sum=True,
                    name=f"Washington Gas{label} {key}",
                    source=DOMAIN,
                    statistic_id=f"{DOMAIN}:{prefix}{key}",
                    unit_class=unit_class,
                    unit_of_measurement=unit,
                ),
                data,
            )
