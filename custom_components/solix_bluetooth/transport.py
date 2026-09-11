"""Maintain a long-lived Bluetooth session with a Solix device."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from contextlib import suppress
from typing import Any

_LOGGER = logging.getLogger(__name__)

# SolixBLE allows itself up to 90 seconds for encryption negotiation, on top of the
# time bleak-retry-connector spends establishing the link through a proxy.
CONNECT_TIMEOUT = 180
# Each notification replaces the device's parameter set, so the group holding a given
# property can lag several packets behind the first one.
TELEMETRY_TIMEOUT = 45
DISCONNECT_TIMEOUT = 10

_DECODE_ERRORS = (KeyError, IndexError, ValueError, TypeError, OverflowError)


class SolixConnection:
    """Hold one Solix BLE connection open and expose its latest telemetry."""

    def __init__(
        self,
        device_factory: Callable[[Any], Any],
        properties: Iterable[str],
        on_telemetry: Callable[[dict[str, Any]], None] | None = None,
        required: Iterable[str] = (),
    ) -> None:
        self._device_factory = device_factory
        self._properties = tuple(properties)
        self._on_telemetry = on_telemetry
        self._required = tuple(required)
        self._device: Any | None = None
        self._values: dict[str, Any] = {}
        self._available = asyncio.Event()
        self._ready = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Whether the open session is still delivering telemetry."""
        return self._device is not None and bool(self._device.available)

    async def async_connect(
        self,
        ble_device: Any,
        timeout: float = CONNECT_TIMEOUT,
        telemetry_timeout: float = TELEMETRY_TIMEOUT,
    ) -> dict[str, Any]:
        """Reuse the open session, reconnecting only once it has dropped."""
        async with self._lock:
            if self.connected:
                return self.snapshot()
            await self._async_close()
            device = self._device_factory(ble_device)
            self._available = asyncio.Event()
            self._ready = asyncio.Event()
            self._device = device
            device.add_callback(self._handle_state_changed)
            try:
                async with asyncio.timeout(timeout):
                    if not await device.connect(max_attempts=2):
                        raise ConnectionError("Unable to negotiate a Solix BLE session")
                    self._handle_state_changed()
                    await self._available.wait()
                # Report whatever arrived rather than failing the session outright.
                with suppress(TimeoutError):
                    async with asyncio.timeout(telemetry_timeout):
                        await self._ready.wait()
            except BaseException:
                await self._async_close()
                raise
            return self.snapshot()

    async def async_disconnect(self) -> None:
        """Release the connection and its Bluetooth proxy slot."""
        async with self._lock:
            await self._async_close()
            self._values.clear()

    def snapshot(self) -> dict[str, Any]:
        """Merge a fresh read into the parameters delivered by earlier packets."""
        device = self._device
        if device is None:
            return dict(self._values)
        for name in self._properties:
            try:
                value = getattr(device, name, None)
            except _DECODE_ERRORS:
                _LOGGER.debug("Unable to decode Solix property %s", name, exc_info=True)
                continue
            if value is not None:
                self._values[name] = value
        return dict(self._values)

    def _handle_state_changed(self) -> None:
        device = self._device
        if device is None or not device.available:
            return
        snapshot = self.snapshot()
        self._available.set()
        if all(snapshot.get(name) is not None for name in self._required):
            self._ready.set()
        if self._on_telemetry is not None:
            self._on_telemetry(snapshot)

    async def _async_close(self) -> None:
        device, self._device = self._device, None
        if device is None:
            return
        device.remove_callback(self._handle_state_changed)
        try:
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await device.disconnect()
        except (TimeoutError, OSError):
            _LOGGER.warning("Unable to cleanly disconnect from Solix device", exc_info=True)


async def async_read_snapshot(
    device_factory: Callable[[Any], Any],
    ble_device: Any,
    properties: Iterable[str],
    required: Iterable[str] = (),
    timeout: float = CONNECT_TIMEOUT,
) -> dict[str, Any]:
    """Read telemetry once and release the connection, for config flow validation."""
    connection = SolixConnection(device_factory, properties, required=required)
    try:
        return await connection.async_connect(ble_device, timeout)
    finally:
        await connection.async_disconnect()
