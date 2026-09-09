"""Coordinate telemetry sessions through Home Assistant's Bluetooth manager."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Any

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_MODEL, CONF_SCAN_INTERVAL
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MODELS, TELEMETRY_PROPERTIES
from .transport import async_read_snapshot

_LOGGER = logging.getLogger(__name__)


class SolixCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch all sensors in one short-lived connection per polling cycle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self.model: str = entry.data[CONF_MODEL]
        self.device_name = entry.title
        self.device_factory = MODELS[self.model]
        self.properties = tuple(
            name
            for name in TELEMETRY_PROPERTIES
            if isinstance(getattr(self.device_factory, name, None), property)
        )
        self._session_task: asyncio.Task | None = None
        self._closing = False

    async def _async_update_data(self) -> dict[str, Any]:
        if self._closing:
            raise UpdateFailed("Integration is shutting down")
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            raise UpdateFailed("Device is not visible to a connectable Bluetooth adapter")
        try:
            self._session_task = self.hass.async_create_task(
                async_read_snapshot(self.device_factory, ble_device, self.properties),
                f"{DOMAIN} telemetry {self.address}",
            )
            return await self._session_task
        except (BleakError, OSError, TimeoutError) as err:
            raise UpdateFailed(f"Unable to read Solix telemetry: {err}") from err
        finally:
            self._session_task = None

    async def async_shutdown(self) -> None:
        """Cancel an active read and release its proxy slot before unloading."""
        self._closing = True
        await super().async_shutdown()
        if task := self._session_task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def async_stop(self, event: Event) -> None:
        """Release the connection when Home Assistant stops."""
        await self.async_shutdown()
