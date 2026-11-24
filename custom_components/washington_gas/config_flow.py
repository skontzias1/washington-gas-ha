"""Config flow for Washington Gas."""

import asyncio
from collections.abc import Mapping
from typing import Any

import aiohttp
from opower.exceptions import ApiException, CannotConnect, InvalidAuth, MfaChallenge
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_THERMS_PER_CCF,
    CONF_USAGE_UNIT,
    DEFAULT_THERMS_PER_CCF,
    DEFAULT_USAGE_UNIT,
    DOMAIN,
    UNIT_CCF,
    UNIT_THERM,
)
from .coordinator import TIMEOUT, async_gas_accounts, create_api

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(
    hass: HomeAssistant, username: str, password: str
) -> dict[str, str]:
    """Try the login; return form errors."""
    try:
        async with asyncio.timeout(TIMEOUT):
            api = create_api(hass, username, password)
            await api.async_login()
            if not await async_gas_accounts(api):
                return {"base": "no_gas_account"}
    except MfaChallenge:
        return {"base": "mfa_not_supported"}
    except InvalidAuth:
        return {"base": "invalid_auth"}
    except (ApiException, CannotConnect, aiohttp.ClientError, TimeoutError):
        return {"base": "cannot_connect"}
    return {}


class WashingtonGasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup and reauth."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the login."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()
            errors = await _validate(
                self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_create_entry(title="Washington Gas", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): PASSWORD,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            errors = await _validate(
                self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "WashingtonGasOptionsFlow":
        """Return the options flow."""
        return WashingtonGasOptionsFlow()


class WashingtonGasOptionsFlow(OptionsFlowWithReload):
    """Set the portal's usage unit and the heat content factor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the units."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USAGE_UNIT,
                        default=self.config_entry.options.get(
                            CONF_USAGE_UNIT, DEFAULT_USAGE_UNIT
                        ),
                    ): vol.In([UNIT_THERM, UNIT_CCF]),
                    vol.Required(
                        CONF_THERMS_PER_CCF,
                        default=self.config_entry.options.get(
                            CONF_THERMS_PER_CCF, DEFAULT_THERMS_PER_CCF
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.8, max=1.3)),
                }
            ),
        )
