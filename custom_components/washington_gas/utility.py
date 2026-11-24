"""Register Washington Gas with the opower library (imported for side effect)."""

from typing import Any

import aiohttp
from opower import get_supported_utility_names
from opower.const import USER_AGENT
from opower.exceptions import CannotConnect, InvalidAuth
from opower.utilities.base import UtilityBase

UTILITY_NAME = "Washington Gas"

# Skip if a later opower release ships its own Washington Gas.
if UTILITY_NAME not in get_supported_utility_names():

    class WashingtonGas(UtilityBase):
        """Opower-hosted portal at wgl.opower.com; sign-in sets a session cookie."""

        @staticmethod
        def name() -> str:
            """Return the name."""
            return UTILITY_NAME

        def subdomain(self) -> str:
            """Return the opower.com subdomain."""
            return "wgl"

        @staticmethod
        def timezone() -> str:
            """Return the timezone."""
            return "America/New_York"

        async def async_login(
            self,
            session: aiohttp.ClientSession,
            username: str,
            password: str,
            login_data: dict[str, Any],
        ) -> None:
            """Sign in."""
            async with session.post(
                "https://wgl.opower.com/ei/edge/apis/user-account-control-v1/cws/v1/wgl/account/signin",
                json={"username": username, "password": password},
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,  # never forward the password elsewhere
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise InvalidAuth("Sign-in rejected")
                resp.raise_for_status()
                if resp.status >= 300:
                    raise CannotConnect(f"Unexpected sign-in status {resp.status}")
