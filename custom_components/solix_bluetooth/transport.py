"""Maintain a long-lived Bluetooth session with a Solix device."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 120
DISCONNECT_TIMEOUT = 10

_DECODE_ERRORS = (KeyError, IndexError, ValueError, TypeError, OverflowError)


class SolixConnection:
    """Hold one Solix BLE connection open and expose its latest telemetry."""

    def __init__(
        self,
        device_factory: Callable[[Any], Any],
        properties: Iterable[str],
        on_telemetry: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._device_factory = device_factory
        self._properties = tuple(properties)
        self._on_telemetry = on_telemetry
        self._device: Any | None = None
        self._ready = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        """Whether the open session is still delivering telemetry."""
        return self._device is not None and bool(self._device.available)

    async def async_connect(
        self, ble_device: Any, timeout: float = CONNECT_TIMEOUT
    ) -> dict[str, Any]:
        """Reuse the open session, reconnecting only once it has dropped."""
        async with self._lock:
            if self.connected:
                return self.snapshot()
            await self._async_close()
            device = self._device_factory(ble_device)
            self._ready = asyncio.Event()
            self._device = device
            device.add_callback(self._handle_state_changed)
            try:
                async with asyncio.timeout(timeout):
                    if not await device.connect(max_attempts=2):
                        raise ConnectionError("Unable to establish a Solix BLE session")
                    self._handle_state_changed()
                    await self._ready.wait()
            except BaseException:
                await self._async_close()
                raise
            return self.snapshot()

    async def async_disconnect(self) -> None:
        """Release the connection and its Bluetooth proxy slot."""
        async with self._lock:
            await self._async_close()

    def snapshot(self) -> dict[str, Any]:
        """Read every supported property off the connected device."""
        device = self._device
        if device is None:
            return {}
        snapshot: dict[str, Any] = {}
        for name in self._properties:
            try:
                snapshot[name] = getattr(device, name, None)
            except _DECODE_ERRORS:
                _LOGGER.debug("Unable to decode Solix property %s", name, exc_info=True)
                snapshot[name] = None
        return snapshot

    def _handle_state_changed(self) -> None:
        device = self._device
        if device is None or not device.available:
            return
        self._ready.set()
        if self._on_telemetry is not None:
            self._on_telemetry(self.snapshot())

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
    timeout: float = CONNECT_TIMEOUT,
) -> dict[str, Any]:
    """Read telemetry once and release the connection, for config flow validation."""
    connection = SolixConnection(device_factory, properties)
    try:
        return await connection.async_connect(ble_device, timeout)
    finally:
        await connection.async_disconnect()
