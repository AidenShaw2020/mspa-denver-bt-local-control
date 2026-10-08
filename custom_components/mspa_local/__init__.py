# SPDX-License-Identifier: Apache-2.0
"""Local MSpa Bluetooth Mesh controls and state."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN
from .coordinator import MSpaCoordinator
from .mesh import Profile

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON,
             Platform.SWITCH, Platform.NUMBER, Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    try:
        profile = Profile.from_dict(entry.options.get("profile", entry.data.get("profile")))
    except ValueError as error:
        raise ConfigEntryError("Invalid MSpa profile") from error
    if entry.unique_id != profile.unique_id:
        raise ConfigEntryError("Profile changed; remove and add MSpa Local again")
    coordinator = MSpaCoordinator(hass, entry, profile)
    if len(profile.app_key)!=16:
        raise ConfigEntryError('Import keys again from the owner account in MSpa Local options')
    for other in hass.data.get(DOMAIN,{}).values():
        if other.source==coordinator.source and other.profile.net_key==profile.net_key:
            raise ConfigEntryError('Use a different controller address for another entry in this Mesh network')
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    coordinator.start_discovery()
    try:await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await coordinator.async_shutdown();raise
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        return True
    return False


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)
