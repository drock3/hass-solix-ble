"""Coordinate telemetry sessions through Home Assistant's Bluetooth manager."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from typing import Any

from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_MODEL, CONF_SCAN_INTERVAL
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MODELS, supported_properties
from .transport import SolixConnection

_LOGGER = logging.getLogger(__name__)


class SolixCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keep one connection open, publish pushed telemetry, and poll as a keepalive."""

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
        self.properties = supported_properties(self.device_factory)
        self._session_task: asyncio.Task | None = None
        self._closing = False
        self._ble_device: Any | None = None
        self._unsubscribe_advertisements: Callable[[], None] | None = None
        self.connection = SolixConnection(
            self.device_factory, self.properties, self._handle_telemetry
        )

    @callback
    def async_track_advertisements(self) -> None:
        """Reconnect as soon as a device that went away starts advertising again."""
        self._unsubscribe_advertisements = bluetooth.async_register_callback(
            self.hass,
            self._handle_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )

    @callback
    def _handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        self._ble_device = service_info.device
        if self._closing or self.connection.healthy:
            return
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _resolve_device(self) -> Any | None:
        """Route to the device, falling back to the adapter that last reached it.

        Solix devices stop advertising while they are connected, so Home Assistant
        drops them from its cache once a long session ends. Retrying through the
        last known route is what turns an outage into a reconnect instead of
        waiting for someone to power cycle the device.
        """
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is not None:
            self._ble_device = ble_device
        elif self._ble_device is not None:
            _LOGGER.debug(
                "%s is not advertising; retrying through its last known adapter",
                self.address,
            )
        return self._ble_device

    @callback
    def _handle_telemetry(self, snapshot: dict[str, Any]) -> None:
        """Publish notifications pushed by the device between polling cycles."""
        if not self._closing:
            self.async_set_updated_data(snapshot)

    async def _async_update_data(self) -> dict[str, Any]:
        if self._closing:
            raise UpdateFailed("Integration is shutting down")
        if self.connection.healthy:
            return self.connection.snapshot()
        ble_device = self._resolve_device()
        if ble_device is None:
            raise UpdateFailed("Device is not visible to a connectable Bluetooth adapter")
        try:
            self._session_task = self.hass.async_create_task(
                self.connection.async_connect(ble_device, resolve=self._resolve_device),
                f"{DOMAIN} telemetry {self.address}",
            )
            return await self._session_task
        except TimeoutError as err:
            raise UpdateFailed(
                f"Timed out establishing a Solix session with {self.address}"
            ) from err
        except (BleakError, OSError) as err:
            raise UpdateFailed(f"Unable to read Solix telemetry: {err}") from err
        finally:
            self._session_task = None

    async def async_shutdown(self) -> None:
        """Cancel an active read and release the proxy slot before unloading."""
        self._closing = True
        if unsubscribe := self._unsubscribe_advertisements:
            self._unsubscribe_advertisements = None
            unsubscribe()
        await super().async_shutdown()
        if task := self._session_task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await self.connection.async_disconnect()

    async def async_stop(self, event: Event) -> None:
        """Release the connection when Home Assistant stops."""
        await self.async_shutdown()
