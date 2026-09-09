"""Config flow tests against the real Home Assistant flow manager."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solix_bluetooth.const import DOMAIN

from .conftest import ADDRESS


async def test_discovery_requires_confirmation(hass, discovery_info):
    with patch("custom_components.solix_bluetooth.config_flow.async_read_snapshot") as read:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery_info
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model"
    read.assert_not_called()


async def test_discovery_creates_entry(hass, discovery_info, bluetooth_device):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery_info
    )
    with (
        patch(
            "custom_components.solix_bluetooth.config_flow.async_read_snapshot",
            new_callable=AsyncMock,
            return_value={"battery_percentage": 72},
        ) as read,
        patch("custom_components.solix_bluetooth.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"model": "C1000"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["address"] == ADDRESS
    assert result["result"].unique_id == ADDRESS.lower()
    assert read.call_args.args[1] is discovery_info.device
    bluetooth_device.assert_called_with(hass, ADDRESS, connectable=True)


async def test_duplicate_device_aborts(hass, discovery_info, config_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery_info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_passive_proxy_rejected(hass, discovery_info):
    discovery_info.connectable = False
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery_info
    )
    assert result["reason"] == "not_supported"


async def test_manual_selection_uses_ha_discovery(hass, discovery_info):
    with patch(
        "homeassistant.components.bluetooth.async_discovered_service_info",
        return_value=[discovery_info],
    ) as discovery:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    discovery.assert_called_with(hass, connectable=True)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": ADDRESS})
    assert result["step_id"] == "model"


async def test_no_devices_found(hass):
    with patch("homeassistant.components.bluetooth.async_discovered_service_info", return_value=[]):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["reason"] == "no_devices_found"


@pytest.mark.parametrize("failure", [ConnectionError, TimeoutError])
async def test_connection_error_recoverable(hass, discovery_info, bluetooth_device, failure):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery_info
    )
    with patch(
        "custom_components.solix_bluetooth.config_flow.async_read_snapshot", side_effect=failure
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"model": "C1000"}
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_invalid_telemetry_rejected(hass, discovery_info, bluetooth_device):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=discovery_info
    )
    with patch(
        "custom_components.solix_bluetooth.config_flow.async_read_snapshot",
        return_value={"battery_percentage": None},
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"model": "C1000"}
        )
    assert result["errors"] == {"base": "invalid_telemetry"}


async def test_polling_options(hass, config_entry):
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {"scan_interval": 120}
