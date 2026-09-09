"""Constants and supported Solix models."""

from SolixBLE import (
    C300,
    C300DC,
    C800,
    C1000,
    C1000G2,
    F2000,
    F2600,
    F3800,
    Solarbank2,
    Solarbank3,
)

DOMAIN = "solix_bluetooth"
DEFAULT_SCAN_INTERVAL = 60
SERVICE_UUID = "0000ff09-0000-1000-8000-00805f9b34fb"

MODELS = {
    "C300": C300,
    "C300DC": C300DC,
    "C800": C800,
    "C1000": C1000,
    "C1000G2": C1000G2,
    "F2000": F2000,
    "F2600": F2600,
    "F3800": F3800,
    "Solarbank2": Solarbank2,
    "Solarbank3": Solarbank3,
}

MODEL_NAMES = {
    "C300": "Solix C300 / C300X",
    "C300DC": "Solix C300 DC / C300X DC",
    "C800": "Solix C800 / C800X",
    "C1000": "Solix C1000 / C1000X",
    "C1000G2": "Solix C1000 Gen 2",
    "F2000": "Solix F2000 / PowerHouse 767",
    "F2600": "Solix F2600",
    "F3800": "Solix F3800",
    "Solarbank2": "Solix Solarbank 2",
    "Solarbank3": "Solix Solarbank 3",
}

POWER_PROPERTIES = (
    "power_in",
    "power_out",
    "ac_power_in",
    "ac_power_out",
    "ac_power_out_sockets",
    "dc_power_out",
    "dc_1_power_out",
    "dc_2_power_out",
    "solar_power_in",
    "solar_pv_1_power_in",
    "solar_pv_2_power_in",
    "solar_pv_3_power_in",
    "solar_pv_4_power_in",
    "battery_charge_power",
    "battery_discharge_power",
    "usb_a1_power",
    "usb_a2_power",
    "usb_c1_power",
    "usb_c2_power",
    "usb_c3_power",
    "usb_c4_power",
)

PERCENTAGE_PROPERTIES = (
    "battery_percentage",
    "battery_percentage_aggregate",
    "battery_percentage_expansion",
    "battery_health",
    "battery_health_expansion",
)

STATUS_PROPERTIES = ("charging_status", "ac_output", "dc_output", "dc_port")

TELEMETRY_PROPERTIES = (
    *POWER_PROPERTIES,
    *PERCENTAGE_PROPERTIES,
    *STATUS_PROPERTIES,
    "temperature",
    "temperature_expansion",
    "time_remaining",
    "num_expansion",
    "serial_number",
    "software_version",
)
