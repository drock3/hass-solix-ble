"""Tests for the long-lived telemetry session."""

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

from bleak.backends.device import BLEDevice
from SolixBLE import C1000

from custom_components.solix_bluetooth.transport import (
    TELEMETRY_STALE_TIMEOUT,
    SolixConnection,
)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the session lifecycle without Bluetooth hardware."""

    def setUp(self):
        self.ble_device = object()
        self.device = Mock(available=True, battery_percentage=72, power_in=0)
        self.device.connect = AsyncMock(return_value=True)
        self.device.disconnect = AsyncMock()
        self.factory = Mock(return_value=self.device)

    def connection(self, properties=(), on_telemetry=None, required=()):
        return SolixConnection(self.factory, properties, on_telemetry, required)

    def stub_missing_battery(self):
        """Make battery_percentage behave like a packet that omits its parameter group."""
        prop = PropertyMock(side_effect=KeyError("c1"))
        type(self.device).battery_percentage = prop
        self.addCleanup(delattr, type(self.device), "battery_percentage")
        return prop

    async def test_uses_supplied_device_and_stays_connected(self):
        connection = self.connection(("battery_percentage", "power_in"))
        result = await connection.async_connect(self.ble_device)
        self.factory.assert_called_once_with(self.ble_device)
        self.assertEqual(result, {"battery_percentage": 72, "power_in": 0})
        self.device.disconnect.assert_not_awaited()
        self.assertTrue(connection.connected)

    async def test_reconnect_is_skipped_while_the_session_is_alive(self):
        connection = self.connection(("battery_percentage",))
        await connection.async_connect(self.ble_device)
        await connection.async_connect(self.ble_device)
        self.factory.assert_called_once_with(self.ble_device)
        self.device.connect.assert_awaited_once()

    async def test_reconnects_after_the_device_drops(self):
        connection = self.connection()
        await connection.async_connect(self.ble_device)
        self.device.available = False
        self.assertFalse(connection.connected)

        async def reconnect(**kwargs):
            self.device.available = True
            return True

        self.device.connect.side_effect = reconnect
        await connection.async_connect(self.ble_device)
        self.assertEqual(self.factory.call_count, 2)
        self.device.disconnect.assert_awaited_once()

    async def test_a_session_that_stops_sending_telemetry_is_rebuilt(self):
        connection = self.connection()
        await connection.async_connect(self.ble_device)
        self.device.last_update = datetime.now() - timedelta(seconds=TELEMETRY_STALE_TIMEOUT + 1)
        self.assertTrue(connection.connected)
        self.assertFalse(connection.healthy)
        await connection.async_connect(self.ble_device)
        self.assertEqual(self.factory.call_count, 2)
        self.device.disconnect.assert_awaited_once()

    async def test_a_recent_packet_keeps_the_session(self):
        connection = self.connection()
        await connection.async_connect(self.ble_device)
        self.device.last_update = datetime.now()
        self.assertTrue(connection.healthy)
        await connection.async_connect(self.ble_device)
        self.factory.assert_called_once_with(self.ble_device)

    async def test_a_retry_asks_for_a_fresh_route(self):
        self.device.connect.return_value = False
        replacement = object()
        with (
            patch("custom_components.solix_bluetooth.transport.RETRY_DELAY", 0),
            self.assertRaises(ConnectionError),
        ):
            await self.connection().async_connect(
                self.ble_device, attempts=2, resolve=lambda: replacement
            )
        self.assertEqual(self.factory.call_args_list[-1].args[0], replacement)

    async def test_disconnect_releases_the_session(self):
        connection = self.connection()
        await connection.async_connect(self.ble_device)
        await connection.async_disconnect()
        self.device.disconnect.assert_awaited_once()
        self.device.remove_callback.assert_called_once_with(
            self.device.add_callback.call_args.args[0]
        )
        self.assertFalse(connection.connected)
        self.assertEqual(connection.snapshot(), {})

    async def test_failed_connection_disconnects(self):
        self.device.connect.return_value = False
        with self.assertRaises(ConnectionError):
            await self.connection().async_connect(self.ble_device, attempts=1)
        self.device.disconnect.assert_awaited_once()

    async def test_a_failed_session_is_retried(self):
        self.device.connect.return_value = False
        with (
            patch("custom_components.solix_bluetooth.transport.RETRY_DELAY", 0),
            self.assertRaises(ConnectionError),
        ):
            await self.connection().async_connect(self.ble_device, attempts=3)
        self.assertEqual(self.device.connect.await_count, 3)

    async def test_waits_for_telemetry_after_connection(self):
        self.device.available = False

        def deliver_telemetry():
            self.device.available = True
            self.device.add_callback.call_args.args[0]()

        async def connect(**kwargs):
            asyncio.get_running_loop().call_soon(deliver_telemetry)
            return True

        self.device.connect.side_effect = connect
        result = await self.connection(("battery_percentage",)).async_connect(self.ble_device)
        self.assertEqual(result["battery_percentage"], 72)

    async def test_pushed_telemetry_is_forwarded(self):
        pushed = []
        connection = self.connection(("battery_percentage",), pushed.append)
        await connection.async_connect(self.ble_device)
        self.device.battery_percentage = 65
        self.device.add_callback.call_args.args[0]()
        self.assertEqual(pushed[-1], {"battery_percentage": 65})

    async def test_missing_telemetry_times_out_and_disconnects(self):
        self.device.available = False
        with self.assertRaises(ConnectionError):
            await self.connection().async_connect(
                self.ble_device, telemetry_timeout=0.01, attempts=1
            )
        self.device.disconnect.assert_awaited_once()

    async def test_values_from_earlier_packets_are_retained(self):
        connection = self.connection(("battery_percentage", "power_in"))
        await connection.async_connect(self.ble_device)
        self.stub_missing_battery()
        self.device.power_in = 45
        self.assertEqual(connection.snapshot(), {"battery_percentage": 72, "power_in": 45})

    async def test_waits_for_the_packet_carrying_a_required_property(self):
        battery = self.stub_missing_battery()

        def deliver_battery():
            battery.side_effect = None
            battery.return_value = 72
            self.device.add_callback.call_args.args[0]()

        async def connect(**kwargs):
            asyncio.get_running_loop().call_soon(deliver_battery)
            return True

        self.device.connect.side_effect = connect
        connection = self.connection(("battery_percentage",), required=("battery_percentage",))
        self.assertEqual(
            await connection.async_connect(self.ble_device), {"battery_percentage": 72}
        )

    async def test_partial_telemetry_is_returned_when_a_required_property_never_arrives(self):
        self.stub_missing_battery()
        connection = self.connection(
            ("battery_percentage", "power_in"), required=("battery_percentage",)
        )
        result = await connection.async_connect(self.ble_device, telemetry_timeout=0.01)
        self.assertEqual(result, {"power_in": 0})
        self.assertTrue(connection.connected)

    async def test_cancellation_disconnects(self):
        self.device.connect.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.connection().async_connect(self.ble_device)
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
        connection = SolixConnection(
            factory, ("battery_percentage", "power_in", "temperature", "battery_health")
        )

        result = await connection.async_connect(ble_device)

        # temperature decodes to the library's -1 sentinel, so it is dropped.
        self.assertEqual(result, {"battery_percentage": 72, "power_in": 0})
        factory.assert_called_once_with(ble_device)
        await connection.async_disconnect()
        device.disconnect.assert_awaited_once()
        self.assertEqual(device._state_changed_callbacks, [])
