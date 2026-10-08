# SPDX-License-Identifier: Apache-2.0
"""Native bubble intensity control."""
from homeassistant.components.number import NumberEntity
from .const import DOMAIN
from .entity import MSpaEntity


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([MSpaBubbleLevel(hass.data[DOMAIN][entry.entry_id])])


class MSpaBubbleLevel(MSpaEntity,NumberEntity):
    _attr_native_min_value=1;_attr_native_max_value=3;_attr_native_step=1
    _attr_icon='mdi:chart-bubble'

    def __init__(self,coordinator):super().__init__(coordinator,'bubble_level','Bubble Level')

    @property
    def native_value(self):return self.coordinator.raw.get('bubble_level')

    async def async_set_native_value(self,value):await self.coordinator.async_set_bubble_level(value)
