# Anker Solix Bluetooth for Home Assistant

A read-only custom integration that brings Anker Solix telemetry into Home Assistant through its Bluetooth stack, including **active ESPHome Bluetooth proxies**. It uses [SolixBLE](https://github.com/flip-dots/SolixBLE) for protocol handling. No Anker account, cloud API, MQTT broker, or Bluetooth adapter on the Home Assistant host is required when using a proxy.

> [!IMPORTANT]
> This is an initial implementation, not a hardware-certified integration. Automated tests mock the radio. Compatibility with your specific device, firmware, and proxy must be verified on hardware. Neither this project nor SolixBLE is affiliated with Anker.

## Requirements

- Home Assistant 2025.8 or newer (Home Assistant OS or a supported Linux installation).
- A configured Bluetooth adapter or ESPHome proxy that supports **active GATT connections**, with a free connection slot.
- Bluetooth enabled on a supported Solix device, within range of the adapter or proxy.
- Disconnect the Anker app and other Bluetooth clients from the device.

An ESPHome proxy must be added to Home Assistant through the ESPHome integration. Its existing configuration should include:

```yaml
esp32_ble_tracker:

bluetooth_proxy:
  active: true
```

This is a configuration fragment for the ESPHome proxy, not Home Assistant's configuration or a complete ESPHome firmware file. Keep your board, network, API, and OTA settings. `bluetooth_proxy.active` enables the GATT connections required to read telemetry. See [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy/).

**Active scanning is separate:** ESPHome defaults `esp32_ble_tracker.scan_parameters.active` to `true`, so explicitly adding it is optional and normally changes nothing. If you previously disabled active scanning, re-enabling it may help discovery by requesting additional advertisement data; it is not an additional setup requirement for this integration.

## Install

Choose HACS or manual installation, then configure the integration below.

### HACS (Custom Repository)

This integration is not in the default HACS catalog, so add it as a custom repository:

1. If HACS is not installed, follow the [HACS download instructions](https://www.hacs.xyz/docs/use/download/download/) and [initial configuration](https://www.hacs.xyz/docs/use/configuration/basic/) first.
2. Open **HACS** in the Home Assistant sidebar.
3. Select the **three-dot menu** in the top-right corner, then **Custom repositories**.
4. Enter `https://github.com/drock3/hass-solix-ble` as the repository URL, select **Integration** as the type, and select **Add**.
5. Close the dialog and search HACS for **Anker Solix Bluetooth**. Open its repository page.
6. Select **Download** and confirm the download when prompted.
7. Restart Home Assistant, then follow **Configure the Integration** below.

Add this URL in HACS, not in Home Assistant's app/add-on repository settings. HACS downloads the integration files; you still need to add the integration in Home Assistant after restarting.

### Manual Installation

1. Put the `custom_components/solix_bluetooth` directory from this repository in `/config/custom_components/solix_bluetooth` on your Home Assistant system. The `manifest.json` file must be directly inside that directory.
2. Restart Home Assistant, then follow **Configure the Integration** below.

### Configure the Integration

1. Open **Settings > Devices & services**. Configure a discovered **Anker Solix Bluetooth** device, or choose **Add integration > Anker Solix Bluetooth**.
2. Select the device and its exact model. Setup verifies a telemetry reading before saving. Allow up to two minutes, plus connection cleanup.

Home Assistant installs the pinned `SolixBLE==3.9.0` dependency automatically. No `configuration.yaml` entry is needed.

## Models and Data

The model selector uses SolixBLE's implementations for C300(X), C300(X) DC, C800(X), C1000(X), C1000 Gen 2, F2000 / PowerHouse 767, F2600, F3800, Solarbank 2, and Solarbank 3. Prime chargers and power banks are not included. A selectable model means library support exists, not that this integration has been hardware-tested with it. See the [upstream support table](https://solixble.readthedocs.io/en/latest/) for model and firmware limitations.

Entities are created only for properties implemented by the selected model:

- Battery percentage, health, and aggregate charge where supported.
- Total, AC, DC, USB, solar, and battery charge/discharge power in watts.
- Battery temperature in Celsius and time remaining in hours.
- Charging and output-port status, plus expansion battery count.
- Expansion battery charge, health, and temperature, disabled by default. Enable them in the device's entity list when needed.

Firmware and serial number appear in device information when available. Missing or undecodable properties show as unknown, not zero. Ambiguous upstream energy counters are deliberately omitted, and no energy totals are calculated from power samples. There are no controls that change power output or charging settings.

## How Connections Work

Every reconnect asks Home Assistant for a current, connectable `BLEDevice`. SolixBLE receives that object, preserving Home Assistant's routing through local adapters or remote proxies. This integration never starts a standalone Bleak scan and never connects using a bare MAC address.

The integration holds **one long-lived connection** and publishes telemetry as the device pushes it, so sensors update as fast as the device reports. A periodic check runs every **60 seconds** by default, adjustable from **30 to 3600 seconds** under the integration's options; it only reconnects when the session has dropped, otherwise it republishes the latest values. Keeping the session open avoids the repeated pairing handshake, which is the main source of dropouts and unavailable sensors.

The connection occupies one proxy or adapter slot for as long as the integration is loaded. Failures mark sensors unavailable until a reconnect succeeds; failed initial setup is retried by Home Assistant. Unload, shutdown, timeout, and cancellation release the session, and a new library device is created for each reconnect, avoiding reuse of its reconnect state.

## Troubleshooting

- **No devices found:** Confirm the proxy is online through Home Assistant's ESPHome integration and `bluetooth_proxy.active` is enabled. Check Home Assistant's Bluetooth advertisement monitor to see whether the station is visible. This integration lists connectable devices advertising the `0000ff09-0000-1000-8000-00805f9b34fb` service. For more discovery information, check SolixBLE's [Finding a device](https://solixble.readthedocs.io/en/latest/usage.html#finding-a-device) section.
- **Bluetooth connection or discovery issues:** Make sure to check SolixBLE's [Bluetooth connection](https://solixble.readthedocs.io/en/latest/limitations.html#bluetooth-connection) section for more information.
- **Bluetooth and Wi-Fi:** See SolixBLE's [Bluetooth and Wi-Fi](https://solixble.readthedocs.io/en/latest/limitations.html#bluetooth-and-wi-fi) section for more information.
- **Proxy connection issues:** Check the proxy's free connection slots and [ESPHome Bluetooth Proxy documentation](https://esphome.io/components/bluetooth_proxy/).
- **Wrong or missing readings:** Check the selected model and compare readings with the station's display. For more information, see SolixBLE's [Updates](https://solixble.readthedocs.io/en/latest/limitations.html#updates) and [Device support](https://solixble.readthedocs.io/en/latest/limitations.html#device-support) sections.
- **Model or firmware issues:** Check SolixBLE's [support tables](https://solixble.readthedocs.io/en/latest/) and [issue tracker](https://github.com/flip-dots/SolixBLE/issues) for more information.
- **Logs:** Look for `custom_components.solix_bluetooth` and `SolixBLE`. Review and redact addresses, serials, and raw protocol data before sharing logs; verbose upstream logs may contain negotiation material.

## Development

Use Linux or WSL for Home Assistant tests. Use the Python version required by the installed Home Assistant test harness (currently Python 3.14 for recent releases).

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
ruff check custom_components tests
ruff format --check custom_components tests
```

Tests cover the real Home Assistant config flow, setup, sensor mapping, polling, recovery, and unload with mocked Bluetooth, plus transport timeout and cancellation cleanup. GitHub Actions runs those tests and Home Assistant's manifest validation.
