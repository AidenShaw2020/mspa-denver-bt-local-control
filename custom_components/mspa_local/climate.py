# SPDX-License-Identifier: Apache-2.0
"""Native heater control and target temperature; no heat prediction."""
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode, HVACAction
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from .const import DOMAIN
from .entity import MSpaEntity


async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([MSpaClimate(hass.data[DOMAIN][entry.entry_id])])


class MSpaClimate(MSpaEntity,ClimateEntity):
    _attr_temperature_unit=UnitOfTemperature.CELSIUS
    _attr_min_temp=20;_attr_max_temp=40;_attr_target_temperature_step=0.5;_attr_precision=0.5
    _attr_hvac_modes=[HVACMode.HEAT,HVACMode.OFF]
    _attr_supported_features=(ClimateEntityFeature.TARGET_TEMPERATURE|ClimateEntityFeature.TURN_ON|ClimateEntityFeature.TURN_OFF)
    _attr_icon='mdi:hot-tub'

    def __init__(self,coordinator):super().__init__(coordinator,'climate','Heater Control')

    @property
    def available(self):return super().available and self.coordinator.raw.get('temperature_unit')==0

    @property
    def current_temperature(self):return (self.coordinator.data or {}).get('water_temperature')

    @property
    def target_temperature(self):return (self.coordinator.data or {}).get('target_temperature')

    @property
    def hvac_mode(self):
        return HVACMode.HEAT if self.coordinator.raw.get('heater_state')==1 else HVACMode.OFF

    @property
    def hvac_action(self):
        if self.coordinator.raw.get('heater_state')!=1:return HVACAction.OFF
        state=self.coordinator.raw.get('heat_state')
        if state in (2,3):return HVACAction.HEATING
        if state==4:return HVACAction.IDLE
        return None

    async def async_set_temperature(self,**kwargs):
        if ATTR_TEMPERATURE in kwargs:await self.coordinator.async_set_temperature(kwargs[ATTR_TEMPERATURE])

    async def async_set_hvac_mode(self,hvac_mode):
        if hvac_mode not in self._attr_hvac_modes:raise ValueError('Unsupported HVAC mode')
        await self.coordinator.async_set_feature('heater',hvac_mode==HVACMode.HEAT)

    async def async_turn_on(self):await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):await self.async_set_hvac_mode(HVACMode.OFF)
