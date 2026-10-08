# SPDX-License-Identifier: Apache-2.0
"""Local Bluetooth controls; no prediction or automatic heating scheduler."""
DOMAIN = "mspa_local"
PROBE_SECONDS = 60
VERSION = '0.2.0'
POLL_SECONDS = 60
CONTROLLER_ADDRESS = '7FFD'
FEATURES = {
    'heater': ('Heater', 'heater_state', 'mdi:hot-tub'),
    'filter': ('Filter', 'filter_state', 'mdi:air-filter'),
    'bubble': ('Bubble', 'bubble_state', 'mdi:chart-bubble'),
    'jet': ('Jet', 'jet_state', 'mdi:turbine'),
    'ozone': ('Ozone', 'ozone_state', 'mdi:weather-hazy'),
    'uvc': ('UVC', 'uvc_state', 'mdi:weather-sunny-alert'),
}
