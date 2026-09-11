"""Read-only sensors for supported Solix telemetry properties."""

import math
from enum import Enum

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SolixConfigEntry
from .const import (
    DOMAIN,
    MODEL_NAMES,
    PERCENTAGE_PROPERTIES,
    POWER_PROPERTIES,
    STATUS_PROPERTIES,
)
from .coordinator import SolixCoordinator

PARALLEL_UPDATES = 0

_ACRONYMS = frozenset({"ac", "dc", "pv", "usb", "a1", "a2", "c1", "c2", "c3", "c4"})


def _title(key: str) -> str:
    """Humanise a library property name, keeping hardware acronyms uppercase."""
    name = " ".join(word.upper() if word in _ACRONYMS else word for word in key.split("_"))
    return name[0].upper() + name[1:]


SENSORS = (
    *(
        SensorEntityDescription(
            key=key,
            name=_title(key),
            native_unit_of_measurement=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
        )
        for key in POWER_PROPERTIES
    ),
    *(
        SensorEntityDescription(
            key=key,
            name=_title(key),
            native_unit_of_measurement=PERCENTAGE,
            device_class=SensorDeviceClass.BATTERY if "percentage" in key else None,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default="expansion" not in key,
        )
        for key in PERCENTAGE_PROPERTIES
    ),
    *(
        SensorEntityDescription(
            key=key,
            name=_title(key),
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_registry_enabled_default="expansion" not in key,
        )
        for key in ("temperature", "temperature_expansion")
    ),
    *(SensorEntityDescription(key=key, name=_title(key)) for key in STATUS_PROPERTIES),
    SensorEntityDescription(
        key="time_remaining",
        name=_title("time_remaining"),
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="num_expansion",
        name="Expansion batteries",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolixConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create only entities whose properties are implemented by this model."""
    coordinator = entry.runtime_data
    async_add_entities(
        SolixSensor(coordinator, description)
        for description in SENSORS
        if description.key in coordinator.properties
    )


class SolixSensor(CoordinatorEntity[SolixCoordinator], SensorEntity):
    """A sensor backed by the last successful telemetry snapshot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolixCoordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.device_name,
            manufacturer="Anker",
            model=MODEL_NAMES[coordinator.model],
            serial_number=self._metadata("serial_number"),
            sw_version=self._metadata("software_version"),
        )

    def _metadata(self, key: str) -> str | None:
        value = self.coordinator.data.get(key)
        return value if isinstance(value, str) and value not in ("", "Unknown") else None

    @property
    def native_value(self) -> int | float | str | None:
        """Translate unknown values without discarding valid subzero temperatures."""
        key = self.entity_description.key
        value = self.coordinator.data.get(key)
        if "expansion" in key and not self.coordinator.data.get("num_expansion"):
            return None
        if isinstance(value, Enum):
            return None if value.name == "UNKNOWN" else value.name.lower()
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                return None
            if self.device_class != SensorDeviceClass.TEMPERATURE and value < 0:
                return None
            if self.native_unit_of_measurement == PERCENTAGE and value > 100:
                return None
            return value
        return None
