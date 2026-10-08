# SPDX-License-Identifier: Apache-2.0
"""Read fresh device state on demand."""
from homeassistant.components.button import ButtonEntity
from .const import DOMAIN
from .entity import MSpaEntity


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([MSpaRefresh(hass.data[DOMAIN][entry.entry_id])])


class MSpaRefresh(MSpaEntity,ButtonEntity):
    _attr_icon='mdi:refresh'
    def __init__(self,coordinator):super().__init__(coordinator,'refresh','Refresh Bluetooth state',diagnostic=True)

    @property
    def available(self):return not self.coordinator.stopping

    async def async_press(self):await self.coordinator.async_probe()
