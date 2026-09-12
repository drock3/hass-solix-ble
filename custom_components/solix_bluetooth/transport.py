"""Maintain a long-lived Bluetooth session with a Solix device."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any

from bleak.exc import BleakError

from .const import is_known

_LOGGER = logging.getLogger(__name__)

# SolixBLE allows itself up to 90 seconds for encryption negotiation, on top of the
# time bleak-retry-connector spends establishing the link through a proxy.
CONNECT_TIMEOUT = 180
# Each notification replaces the device's parameter set, so the group holding a given
# property can lag several packets behind the first one.
TELEMETRY_TIMEOUT = 45
DISCONNECT_TIMEOUT = 10
# Proxied links routinely drop mid-negotiation with GATT error 133, which leaves the
# session unusable; only a fresh link recovers it.
CONNECT_ATTEMPTS = 3
RETRY_DELAY = 5
# A wedged proxy keeps reporting a live link long after the device stopped talking,
# so a session that has gone quiet has to be treated as dead on its own merit.
TELEMETRY_STALE_TIMEOUT = 180

_DECODE_ERRORS = (KeyError, IndexError, ValueError, TypeError, OverflowError)
_SESSION_ERRORS = (BleakError, OSError, TimeoutError)


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
        """Whether the session is negotiated and has parameters to report."""
        return self._device is not None and bool(self._device.available)

    @property
    def telemetry_age(self) -> float | None:
        """Seconds since the device last sent a packet, if it ever has."""
        stamp = getattr(self._device, "last_update", None)
        if not isinstance(stamp, datetime):
            return None
        return max(0.0, (datetime.now() - stamp).total_seconds())

    @property
    def healthy(self) -> bool:
        """Whether the session is up and packets are still arriving."""
        if not self.connected:
            return False
        age = self.telemetry_age
        return age is None or age < TELEMETRY_STALE_TIMEOUT

    async def async_connect(
        self,
        ble_device: Any,
        timeout: float = CONNECT_TIMEOUT,
        telemetry_timeout: float = TELEMETRY_TIMEOUT,
        attempts: int = CONNECT_ATTEMPTS,
        resolve: Callable[[], Any | None] | None = None,
    ) -> dict[str, Any]:
        """Reuse the open session, reconnecting once it drops or falls silent."""
        async with self._lock:
            if self.healthy:
                return self.snapshot()
            if self.connected:
                _LOGGER.info(
                    "Solix session still looks connected but has sent no telemetry "
                    "for %s seconds; rebuilding it",
                    TELEMETRY_STALE_TIMEOUT,
                )
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                if attempt > 1 and resolve is not None:
                    # The proxy that served the last attempt may have gone away.
                    ble_device = resolve() or ble_device
                try:
                    return await self._async_open(ble_device, timeout, telemetry_timeout)
                except _SESSION_ERRORS as err:
                    last_error = err
                    _LOGGER.debug(
                        "Solix session attempt %s of %s failed: %s",
                        attempt,
                        attempts,
                        str(err) or type(err).__name__,
                    )
                    if attempt < attempts:
                        await asyncio.sleep(RETRY_DELAY)
            raise last_error

    async def _async_open(
        self,
        ble_device: Any,
        timeout: float,
        telemetry_timeout: float,
    ) -> dict[str, Any]:
        """Establish one session from scratch, tearing it down if anything fails."""
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
            try:
                async with asyncio.timeout(telemetry_timeout):
                    await self._available.wait()
            except TimeoutError:
                raise ConnectionError(
                    "Negotiated a Solix BLE session but the device sent no "
                    "telemetry; the configured model is probably wrong"
                ) from None
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
            if is_known(value):
                self._values[name] = value
        return dict(self._values)

    def _handle_state_changed(self) -> None:
        device = self._device
        if device is None or not device.available:
            return
        snapshot = self.snapshot()
        self._available.set()
        if all(is_known(snapshot.get(name)) for name in self._required):
            self._ready.set()
        if self._on_telemetry is not None:
            self._on_telemetry(snapshot)

    async def _async_close(self) -> None:
        device, self._device = self._device, None
        if device is None:
            return
        # Never let bookkeeping skip the disconnect; a leaked link keeps the
        # device's only connection slot busy until it is power cycled.
        with suppress(ValueError):
            device.remove_callback(self._handle_state_changed)
        try:
            async with asyncio.timeout(DISCONNECT_TIMEOUT):
                await device.disconnect()
        except _SESSION_ERRORS:
            _LOGGER.warning("Unable to cleanly disconnect from Solix device", exc_info=True)


async def async_read_snapshot(
    device_factory: Callable[[Any], Any],
    ble_device: Any,
    properties: Iterable[str],
    required: Iterable[str] = (),
    timeout: float = CONNECT_TIMEOUT,
    attempts: int = 1,
) -> dict[str, Any]:
    """Read telemetry once and release the connection, for config flow validation."""
    connection = SolixConnection(device_factory, properties, required=required)
    try:
        return await connection.async_connect(ble_device, timeout, attempts=attempts)
    finally:
        await connection.async_disconnect()
