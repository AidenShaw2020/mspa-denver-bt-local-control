# SPDX-License-Identifier: Apache-2.0
"""Device readings matching the cloud's native entities; no calculated ETAs."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN
from .entity import MSpaEntity
from .protocol import ATTRIBUTES

RAW_KEYS=sorted(set(ATTRIBUTES.values())-{'water_temperature','temperature_setting','bubble_level','fault'})


async def async_setup_entry(hass,entry,async_add_entities):
    coordinator=hass.data[DOMAIN][entry.entry_id]
    entities=[MSpaSensor(coordinator,key,name,kind) for key,name,kind in (
        ('water_temperature','Water Temperature','temperature'),
        ('fault','Fault','fault'),('filter_status','Filter status','filter'),
        ('heat_time','Heater timer remaining','timer'),
        ('firmware_version','Firmware version','firmware'),
    )]
    entities.extend(MSpaSensor(coordinator,key,key.replace('_',' ').title(),'raw') for key in RAW_KEYS)
    entities.extend(MSpaSensor(coordinator,key,name,'diagnostic') for key,name in (
        ('status','Bluetooth status'),('rssi','Bluetooth signal'),('iv_index','IV Index')))
    async_add_entities(entities)


class MSpaSensor(MSpaEntity,SensorEntity):
    def __init__(self,coordinator,key,name,kind):
        super().__init__(coordinator,'sensor_'+key+'_'+kind,name,diagnostic=kind in ('fault','filter','firmware','raw','diagnostic'))
        self.kind=kind;self.key=key
        if kind=='temperature':
            self._attr_native_unit_of_measurement=UnitOfTemperature.CELSIUS
            self._attr_device_class=SensorDeviceClass.TEMPERATURE
            self._attr_state_class=SensorStateClass.MEASUREMENT
        elif kind=='timer':
            self._attr_native_unit_of_measurement='h';self._attr_state_class=SensorStateClass.MEASUREMENT
        elif kind=='diagnostic' and key=='rssi':
            self._attr_native_unit_of_measurement='dBm';self._attr_device_class=SensorDeviceClass.SIGNAL_STRENGTH

    @property
    def native_value(self):
        data=self.coordinator.data or {};raw=self.coordinator.raw
        if self.kind=='temperature':return data.get(self.key)
        if self.kind=='fault':
            value=raw.get('fault');return None if value is None else 'OK' if value==0 else f'{value:02X}'
        if self.kind=='filter':
            value=raw.get('warning');return None if value is None else 'Dirty' if value==0xA0 else 'OK'
        if self.kind=='firmware':
            p=self.coordinator.profile
            return '-'.join(v for v in (p.wifi_version,p.mcu_version.removeprefix('mcu-')) if v) or None
        if self.kind=='diagnostic':return self.coordinator.diagnostic.get(self.key)
        return raw.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key=='status':return {'last_seen':self.coordinator.last_seen,
            **{k:v for k,v in self.coordinator.diagnostic.items() if k!='address'}}
        return None
