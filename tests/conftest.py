"""Fixtures for tests using Home Assistant with no Bluetooth hardware."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from bleak.backends.device import BLEDevice
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
)

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from custom_components.solix_bluetooth.const import DOMAIN, SERVICE_UUID

ADDRESS = "AA:BB:CC:DD:EE:FF"


@pytest.fixture(autouse=True)
def integration_enabled(hass, enable_custom_integrations):
    """Skip adapter setup while retaining Home Assistant's actual integration APIs."""
    mock_integration(hass, MockModule("bluetooth_adapters"))


@pytest.fixture
def discovery_info():
    """A connectable advertisement originating from a remote proxy."""
    device = BLEDevice(ADDRESS, "Anker SOLIX C1000", {"source": "proxy-kitchen"})
    return BluetoothServiceInfoBleak(
        name=device.name,
        address=ADDRESS,
        rssi=-55,
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        source="proxy-kitchen",
        device=device,
        advertisement=None,
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture
def config_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Anker SOLIX C1000",
        unique_id=ADDRESS.lower(),
        data={"address": ADDRESS, "model": "C1000", "name": "Anker SOLIX C1000"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def snapshot():
    return {
        "battery_percentage": 72,
        "power_in": 0,
        "power_out": 250,
        "temperature": -1,
        "time_remaining": 2.5,
        "serial_number": "TEST1234",
        "software_version": "1.2.3",
        "num_expansion": 0,
    }


@pytest.fixture
def bluetooth_device(discovery_info):
    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address",
        return_value=discovery_info.device,
    ) as lookup:
        yield lookup


@pytest.fixture
def mock_snapshot(snapshot):
    """Replace the persistent connection with one that returns a canned snapshot."""
    read = AsyncMock(return_value=snapshot)

    def build(device_factory, properties, on_telemetry=None):
        connection = Mock(connected=False)

        async def async_connect(ble_device, **kwargs):
            return await read(device_factory, ble_device, properties)

        connection.async_connect = AsyncMock(side_effect=async_connect)
        connection.async_disconnect = AsyncMock()
        connection.snapshot = Mock(return_value=snapshot)
        return connection

    with patch("custom_components.solix_bluetooth.coordinator.SolixConnection", side_effect=build):
        yield read
