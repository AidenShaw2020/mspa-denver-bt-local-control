# SPDX-License-Identifier: Apache-2.0
"""Native heater timer and Mesh authentication diagnostics."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from .const import DOMAIN
from .entity import MSpaEntity


async def async_setup_entry(hass,entry,async_add_entities):
    coordinator=hass.data[DOMAIN][entry.entry_id]
    async_add_entities([MSpaBinarySensor(coordinator,key,name,diagnostic) for key,name,diagnostic in (
        ('heat_time_switch','Heater timer',False),
        ('netkey_verified','Mesh network authenticated',True),
        ('appkey_verified','Mesh application authenticated',True),
    )])


class MSpaBinarySensor(MSpaEntity,BinarySensorEntity):
    def __init__(self,coordinator,key,name,diagnostic):
        super().__init__(coordinator,'binary_'+key,name,diagnostic=diagnostic)
        self.key=key;self.diagnostic=diagnostic

    @property
    def is_on(self):
        data=self.coordinator.diagnostic if self.diagnostic else self.coordinator.raw
        return bool(data.get(self.key))
