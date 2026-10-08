# SPDX-License-Identifier: Apache-2.0
"""The same six feature switches as the cloud integration."""
from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN, FEATURES
from .entity import MSpaEntity


async def async_setup_entry(hass,entry,async_add_entities):
    coordinator=hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MSpaSwitch(coordinator,feature) for feature in FEATURES])


class MSpaSwitch(MSpaEntity,SwitchEntity):
    def __init__(self,coordinator,feature):
        name,self.attribute,icon=FEATURES[feature]
        super().__init__(coordinator,feature,name)
        self.feature=feature;self._attr_icon=icon

    @property
    def available(self):return super().available and self.attribute in self.coordinator.raw

    @property
    def is_on(self):return self.coordinator.raw.get(self.attribute)==1

    async def async_turn_on(self,**kwargs):await self.coordinator.async_set_feature(self.feature,True)

    async def async_turn_off(self,**kwargs):await self.coordinator.async_set_feature(self.feature,False)
