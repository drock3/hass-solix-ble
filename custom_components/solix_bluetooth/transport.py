"""Read a telemetry snapshot using an already discovered Bluetooth device."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Any

_LOGGER = logging.getLogger(__name__)


async def async_read_snapshot(
    device_factory: Callable,
    ble_device: Any,
    properties: Iterable[str],
    timeout: float = 120,
) -> dict[str, Any]:
    """Connect, wait for telemetry, and release the Bluetooth connection."""
    device = device_factory(ble_device)
    ready = asyncio.Event()

    def state_changed() -> None:
        if device.available:
            ready.set()

    device.add_callback(state_changed)
    try:
        async with asyncio.timeout(timeout):
            if not await device.connect(max_attempts=2):
                raise ConnectionError("Unable to establish a Solix BLE session")
            state_changed()
            await ready.wait()
            if not device.available:
                raise ConnectionError("Solix disconnected before telemetry was read")
            snapshot = {}
            for name in properties:
                try:
                    snapshot[name] = getattr(device, name, None)
                except (KeyError, IndexError, ValueError, TypeError, OverflowError):
                    _LOGGER.debug("Unable to decode Solix property %s", name, exc_info=True)
                    snapshot[name] = None
            return snapshot
    finally:
        device.remove_callback(state_changed)
        try:
            async with asyncio.timeout(10):
                await device.disconnect()
        except (TimeoutError, OSError):
            _LOGGER.warning("Unable to cleanly disconnect from Solix device", exc_info=True)
