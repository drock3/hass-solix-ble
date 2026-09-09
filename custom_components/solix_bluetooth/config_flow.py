"""Configure a Solix device discovered by Home Assistant Bluetooth."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_MODEL, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MODEL_NAMES, MODELS, SERVICE_UUID
from .transport import async_read_snapshot

_LOGGER = logging.getLogger(__name__)


class SolixBluetoothConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one supported Solix power station or Solarbank."""

    VERSION = 1

    def __init__(self) -> None:
        self._devices: dict[str, bluetooth.BluetoothServiceInfoBleak] = {}
        self._address = ""
        self._name = ""

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Confirm discovery without opening a connection automatically."""
        if not discovery_info.connectable or SERVICE_UUID not in discovery_info.service_uuids:
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_model()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Select from devices already seen by Home Assistant or its proxies."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._name = self._devices[self._address].name
            await self.async_set_unique_id(format_mac(self._address))
            self._abort_if_unique_id_configured()
            return await self.async_step_model()

        configured = self._async_current_ids()
        self._devices = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if SERVICE_UUID in info.service_uuids
            and info.connectable
            and format_mac(info.address) not in configured
        }
        if not self._devices:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name} ({address})"
                            for address, info in self._devices.items()
                        }
                    )
                }
            ),
        )

    async def async_step_model(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the model explicitly and verify a telemetry session."""
        errors: dict[str, str] = {}
        if user_input is not None:
            model = user_input[CONF_MODEL]
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            if ble_device is None:
                errors["base"] = "cannot_connect"
            else:
                try:
                    snapshot = await async_read_snapshot(
                        MODELS[model], ble_device, ("battery_percentage",)
                    )
                    percentage = snapshot.get("battery_percentage")
                    if not isinstance(percentage, (int, float)) or not 0 <= percentage <= 100:
                        errors["base"] = "invalid_telemetry"
                except (BleakError, OSError, TimeoutError):
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error validating Solix telemetry")
                    errors["base"] = "unknown"
                if not errors:
                    return self.async_create_entry(
                        title=self._name or MODEL_NAMES[model],
                        data={
                            CONF_ADDRESS: self._address,
                            CONF_MODEL: model,
                            CONF_NAME: self._name,
                        },
                    )
        return self.async_show_form(
            step_id="model",
            data_schema=vol.Schema({vol.Required(CONF_MODEL): vol.In(MODEL_NAMES)}),
            description_placeholders={"name": self._name, "address": self._address},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SolixOptionsFlow:
        """Return the polling options flow."""
        return SolixOptionsFlow()


class SolixOptionsFlow(OptionsFlow):
    """Configure the interval between telemetry snapshots."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600))
                }
            ),
        )
