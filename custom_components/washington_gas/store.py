"""Cached bills, so history outlives what the portal still serves."""

from dataclasses import asdict
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .bills import Bill
from .const import DOMAIN

# Version 1 held the bills of the only account.
LEGACY_KEY = "legacy"


class BillStore(Store[dict[str, list[dict[str, Any]]]]):
    """Bills per account slot."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize."""
        super().__init__(hass, 2, f"{DOMAIN}.{entry_id}", private=True)

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: Any
    ) -> dict[str, list[dict[str, Any]]]:
        """Move the version 1 list under the legacy slot."""
        return {
            LEGACY_KEY: [
                {
                    "start": b["start"],
                    "end": b["end"],
                    "usage": b["therms"],
                    "cost": b["cost"],
                }
                for b in old_data
            ]
        }

    async def async_load_bills(self) -> dict[str, list[Bill]]:
        """Load bills."""
        return {
            slot: [
                Bill(
                    date.fromisoformat(b["start"]),
                    date.fromisoformat(b["end"]),
                    b["usage"],
                    b["cost"],
                )
                for b in bills
            ]
            for slot, bills in (await self.async_load() or {}).items()
        }

    async def async_save_bills(self, data: dict[str, list[Bill]]) -> None:
        """Save bills."""
        await self.async_save(
            {
                slot: [
                    {
                        **asdict(b),
                        "start": b.start.isoformat(),
                        "end": b.end.isoformat(),
                    }
                    for b in bills
                ]
                for slot, bills in data.items()
            }
        )
