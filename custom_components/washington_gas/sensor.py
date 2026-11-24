"""Washington Gas sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bills import Bill
from .const import CONF_USAGE_UNIT, DEFAULT_USAGE_UNIT, DOMAIN
from .coordinator import WashingtonGasConfigEntry, WashingtonGasCoordinator
from .store import LEGACY_KEY


@dataclass(frozen=True, kw_only=True)
class BillSensorDescription(SensorEntityDescription):
    """Describe a bill sensor."""

    value: Callable[[Bill], float | date | None]


SENSORS = (
    BillSensorDescription(
        key="last_bill_usage",
        translation_key="last_bill_usage",
        icon="mdi:fire",
        value=lambda b: b.usage,
    ),
    BillSensorDescription(
        key="last_bill_cost",
        translation_key="last_bill_cost",
        native_unit_of_measurement="USD",
        device_class=SensorDeviceClass.MONETARY,
        value=lambda b: b.cost,
    ),
    BillSensorDescription(
        key="last_bill_rate",
        translation_key="last_bill_rate",
        icon="mdi:cash",
        value=lambda b: round(b.cost / b.usage, 4) if b.usage else None,
    ),
    BillSensorDescription(
        key="last_bill_start",
        translation_key="last_bill_start",
        device_class=SensorDeviceClass.DATE,
        value=lambda b: b.start,
    ),
    BillSensorDescription(
        key="last_bill_end",
        translation_key="last_bill_end",
        device_class=SensorDeviceClass.DATE,
        value=lambda b: b.end - timedelta(days=1),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WashingtonGasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        """Add sensors for accounts not seen before."""
        new = set(coordinator.data or {}) - known
        known.update(new)
        async_add_entities(
            BillSensor(coordinator, slot, d) for slot in sorted(new) for d in SENSORS
        )

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class BillSensor(CoordinatorEntity[WashingtonGasCoordinator], SensorEntity):
    """A value from an account's latest bill."""

    entity_description: BillSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WashingtonGasCoordinator,
        slot: str,
        description: BillSensorDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._slot = slot
        self.entity_description = description
        entry = coordinator.config_entry
        base = entry.entry_id if slot == LEGACY_KEY else f"{entry.entry_id}_{slot}"
        unit = entry.options.get(CONF_USAGE_UNIT, DEFAULT_USAGE_UNIT)
        if description.key == "last_bill_usage":
            self._attr_native_unit_of_measurement = unit
        elif description.key == "last_bill_rate":
            self._attr_native_unit_of_measurement = f"USD/{unit}"
        self._attr_unique_id = f"{base}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base)},
            name="Washington Gas"
            if slot == LEGACY_KEY or len(coordinator.data) == 1
            else f"Washington Gas {slot}",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Keep the last bill while the site is down."""
        return bool(self.coordinator.data.get(self._slot))

    @property
    def native_value(self) -> float | date | None:
        """Return the value."""
        return self.entity_description.value(self.coordinator.data[self._slot][-1])
