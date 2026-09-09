"""Integration setup, sensor, recovery, and shutdown tests."""

import asyncio
from unittest.mock import patch

import pytest
from bleak.exc import BleakError
from SolixBLE import C1000
from SolixBLE.states import PortStatus

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solix_bluetooth.coordinator import SolixCoordinator
from custom_components.solix_bluetooth.sensor import SENSORS, SolixSensor

from .conftest import ADDRESS


async def test_setup_sensors_and_unload(
    hass, config_entry, bluetooth_device, mock_snapshot, discovery_info
):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    bluetooth_device.assert_called_with(hass, ADDRESS, connectable=True)
    assert mock_snapshot.call_args.args[0] is C1000
    assert mock_snapshot.call_args.args[1] is discovery_info.device
    states = hass.states.async_all("sensor")
    assert any(state.state == "72" for state in states)
    assert any(
        state.state == "0" and state.attributes.get("unit_of_measurement") == "W"
        for state in states
    )
    assert any(
        state.state == "-1" and state.attributes.get("device_class") == "temperature"
        for state in states
    )
    assert not any("usb_c3" in state.entity_id for state in states)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_no_connectable_device(hass, config_entry, bluetooth_device):
    bluetooth_device.return_value = None
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_refresh_resolves_proxy_again(hass, config_entry, bluetooth_device, mock_snapshot):
    coordinator = SolixCoordinator(hass, config_entry)
    await coordinator.async_refresh()
    replacement = object()
    bluetooth_device.return_value = replacement
    await coordinator.async_refresh()
    assert mock_snapshot.call_args.args[1] is replacement
    assert bluetooth_device.call_count == 2
    await coordinator.async_shutdown()


async def test_failed_refresh_and_recovery(hass, config_entry, bluetooth_device, mock_snapshot):
    coordinator = SolixCoordinator(hass, config_entry)
    await coordinator.async_refresh()
    mock_snapshot.side_effect = BleakError("proxy offline")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    mock_snapshot.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    await coordinator.async_shutdown()


async def test_shutdown_cancels_active_read(hass, config_entry, bluetooth_device):
    coordinator = SolixCoordinator(hass, config_entry)
    started = asyncio.Event()
    cleaned_up = asyncio.Event()

    async def read(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned_up.set()

    with patch("custom_components.solix_bluetooth.coordinator.async_read_snapshot", read):
        task = asyncio.create_task(coordinator._async_update_data())
        await started.wait()
        await coordinator.async_shutdown()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert cleaned_up.is_set()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("power_in", 0, 0),
        ("power_in", -1, None),
        ("power_in", float("nan"), None),
        ("battery_percentage", 101, None),
        ("battery_percentage", 0, 0),
        ("temperature", -1, -1),
        ("temperature", -10, -10),
        ("ac_output", PortStatus.OUTPUT, "output"),
        ("temperature_expansion", 0, None),
        ("battery_percentage_expansion", 0, None),
    ],
)
async def test_sensor_values(hass, config_entry, snapshot, key, value, expected):
    coordinator = SolixCoordinator(hass, config_entry)
    coordinator.data = {**snapshot, key: value}
    sensor = SolixSensor(coordinator, next(item for item in SENSORS if item.key == key))
    assert sensor.native_value == expected
    assert sensor.unique_id == f"{ADDRESS}_{key}"
    coordinator.last_update_success = False
    assert not sensor.available
    await coordinator.async_shutdown()
