"""Tests for proxy-safe telemetry sessions."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from bleak.backends.device import BLEDevice
from SolixBLE import C1000

from custom_components.solix_bluetooth.transport import async_read_snapshot


class TransportTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the session lifecycle without Bluetooth hardware."""

    def setUp(self):
        self.ble_device = object()
        self.device = Mock(available=True, battery_percentage=72, power_in=0)
        self.device.connect = AsyncMock(return_value=True)
        self.device.disconnect = AsyncMock()
        self.factory = Mock(return_value=self.device)

    async def test_uses_supplied_device_and_disconnects(self):
        result = await async_read_snapshot(
            self.factory, self.ble_device, ("battery_percentage", "power_in")
        )
        self.factory.assert_called_once_with(self.ble_device)
        self.assertEqual(result, {"battery_percentage": 72, "power_in": 0})
        self.device.disconnect.assert_awaited_once()
        self.device.remove_callback.assert_called_once_with(
            self.device.add_callback.call_args.args[0]
        )

    async def test_failed_connection_disconnects(self):
        self.device.connect.return_value = False
        with self.assertRaises(ConnectionError):
            await async_read_snapshot(self.factory, self.ble_device, ())
        self.device.disconnect.assert_awaited_once()

    async def test_waits_for_telemetry_after_connection(self):
        self.device.available = False

        def deliver_telemetry():
            self.device.available = True
            self.device.add_callback.call_args.args[0]()

        async def connect(**kwargs):
            asyncio.get_running_loop().call_soon(deliver_telemetry)
            return True

        self.device.connect.side_effect = connect
        result = await async_read_snapshot(self.factory, self.ble_device, ("battery_percentage",))
        self.assertEqual(result["battery_percentage"], 72)

    async def test_missing_telemetry_times_out_and_disconnects(self):
        self.device.available = False
        with self.assertRaises(TimeoutError):
            await async_read_snapshot(self.factory, self.ble_device, (), timeout=0.01)
        self.device.disconnect.assert_awaited_once()

    async def test_cancellation_disconnects(self):
        self.device.connect.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await async_read_snapshot(self.factory, self.ble_device, ())
        self.device.disconnect.assert_awaited_once()

    async def test_real_library_parser_tolerates_missing_fields(self):
        ble_device = BLEDevice("AA:BB:CC:DD:EE:FF", "C1000", {"source": "proxy"})
        device = C1000(ble_device)
        device._client = Mock(is_connected=True)
        device._shared_secret = bytes(32)
        device._data = {
            "c1": bytes.fromhex("0148"),
            "af": bytes.fromhex("0100"),
            "bd": bytes.fromhex("01ff"),
        }
        device.connect = AsyncMock(return_value=True)
        device.disconnect = AsyncMock()
        factory = Mock(return_value=device)

        result = await async_read_snapshot(
            factory,
            ble_device,
            ("battery_percentage", "power_in", "temperature", "battery_health"),
        )

        self.assertEqual(
            result,
            {"battery_percentage": 72, "power_in": 0, "temperature": -1, "battery_health": None},
        )
        factory.assert_called_once_with(ble_device)
        device.disconnect.assert_awaited_once()
        self.assertEqual(device._state_changed_callbacks, [])
