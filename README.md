# Husdata H66 for Home Assistant

A Home Assistant custom integration for the [Husdata H66](https://husdata.se/produkt/h66-wifi-eth-gateway-styr-din-varmepump/) heat pump gateway. It talks to the H66 over Modbus TCP and gives every value a proper entity, instead of the `climate` "thermostats" the H66 creates for its settings with MQTT discovery:

- Temperatures, operating hours, power and energy as sensors
- Compressor, pumps, switch valve and alarm as binary sensors
- Settings as numbers and switches with real limits and units
- Alarm reset as a button

It uses Home Assistant's own Modbus connection handling (2026.10 or newer) and the [husdata-h66-modbus](https://pypi.org/project/husdata-h66-modbus/) library. It is tested with an IVT Greenline (Rego 600 controller), and reads the register map from the H66 web page, so other heat pumps the H66 supports should work too.

## Before you start

Modbus TCP is off in the H66 by default:

1. Open the H66 web page, then **Config** > **Modbus**
2. Set `MODBUS_PORT` to `502`
3. Restart the H66

The H66 accepts only one Modbus client at a time. Home Assistant keeps its connection open, so other Modbus tools can't connect while the integration is running. The H66's MQTT output is separate and keeps working.

## Installation

### Marketplace (recommended)

Husdata H66 isn't listed in the Home Assistant Marketplace yet, so you add this repository to it as a custom repository first (Home Assistant 2026.11 or newer).

Click the button to open this repository in the Marketplace, and confirm when Home Assistant asks to add it as a custom repository:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jonnybergdahl&category=Integration&repository=HomeAssistant_Husdata_H66_Modbus_Integration)

Or add it by hand:

1. Go to **Settings** > **Marketplace**
2. Open the menu (⋮) in the top right corner and select **Custom repositories**
3. Enter `https://github.com/jonnybergdahl/HomeAssistant_Husdata_H66_Modbus_Integration` as the repository, select **Integration** as the type, and select **Add**
4. Search for **Husdata H66** and open it
5. Select **Install**, check the version, and select **Install** again

No restart is needed. Home Assistant goes straight to the setup flow described below.

> On Home Assistant 2026.10, use HACS instead: in HACS, open the menu (⋮) > **Custom repositories**, add the repository URL above with the type **Integration**, then search for **Husdata H66**, click **Download**, and restart Home Assistant. Older versions aren't supported.

### Manual

1. Copy the `custom_components/husdata_h66` folder into your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Setup

Click the button to add a Husdata H66 to Home Assistant.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=husdata_h66)

You can also set it up manually:

1. Go to **Settings** > **Devices & services** > **Add integration**
2. Search for **Husdata H66**
3. Enter the H66's host name or IP address. Keep port `502` and unit ID `1` unless you changed them in the H66.
4. Click **Submit**

> To change the polling interval (default 30 seconds), open the integration's **Configure** action. If the H66's address changes, use **Reconfigure**.

## How it works

The H66 numbers its Modbus registers one per parameter, in the order of its home page, so the addresses depend on the heat pump and can move after an H66 firmware update or when you add custom registers. The integration reads the register map, firmware version, controller and MAC address from the H66 home page when you add it and every time it starts. If the page can't be read, it uses the map it stored last time.

Custom registers you add in the H66 show up as sensors, named as on the H66 web page.

## Entities

Names below are for a Rego 600, with the meanings from Husdata's [variable list for Rego 600/637](https://online.husdata.se/h-docs/C00.pdf). Entities only appear for registers your H66 has. The integration is translated to English and Swedish, and follows your Home Assistant language.

| Entity | Type | Notes |
|---|---|---|
| Radiator return/forward, Heat carrier return/forward, Brine in/out, Outdoor/Indoor temperature, Hot water top/middle, Hot gas | Sensor | °C. A sensor the H66 reports as missing (−48.3 °C) is disabled by default |
| Heating setpoint, Hot water setpoint | Sensor | Calculated by the heat pump |
| Additional heat | Sensor | Electric heater, % |
| Power consumption, Accumulated consumption | Sensor | Calculated by the H66 from the wattages set on its web page. Accumulated consumption restarts at 0 when the H66 boots, which the Energy dashboard handles |
| Compressor/Electric heater hours heating/hot water | Sensor | Diagnostic |
| Last alarm | Sensor | The last alarm that triggered, even if no alarm is active now, as text. The raw code is in the `code` attribute |
| Room sensor influence | Sensor | Diagnostic, disabled by default |
| Compressor, Additional heat step 1/2, Brine pump, Heat carrier pump, Radiator pump | Binary sensor | Running |
| Hot water production | Binary sensor | The switch valve: on while making hot water, off while heating the radiators |
| Alarm | Binary sensor | Problem |
| Room temperature setpoint | Number | 5–29 °C |
| Extra hot water | Number | 0–1440 min, in whole hours |
| Summer mode outdoor temperature | Number | 0–30 °C |
| Holiday mode | Number | 0–30 days. Disabled by default, since how the H66 stores it isn't verified yet. While it's active, set it to 0 before setting a new value |
| Heat curve, Heat curve parallel offset, Hot water stop temperature, Hot water start difference | Number | Config |
| Electric heater max power | Select | 3, 6 or 9 kW. Config |
| Electric heater allowed | Switch | Takes effect the next time the electric heater would start. Config |
| External control | Switch | Config, disabled by default. The H66 can't read it back, so it shows what you last set. Husdata warns it can behave unpredictably on a Rego 600 |
| Reset alarm | Button | Turns the heat pump off for 10 seconds and on again |

## Development

```bash
uv venv --python 3.14 && uv pip install -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## License

MIT
