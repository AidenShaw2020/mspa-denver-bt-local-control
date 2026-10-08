"""Protocol and HA-adapter tests, with encrypted synthetic BLE peripherals."""
import asyncio
from datetime import datetime,timezone
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'custom_components/mspa_local'
pkg=ModuleType('local02');pkg.__path__=[str(PKG)];sys.modules['local02']=pkg
m=importlib.import_module('local02.mesh')
t=importlib.import_module('local02.transport')
p=importlib.import_module('local02.protocol')
NET=bytes.fromhex('7dd7364cd842ad18c17c2b820c84c3d6')
APP=bytes.fromhex('3216d1509884b533248541792b877f98')
PROFILE=m.Profile('Test','Test model','test-uuid',0x0102,NET,APP)


class Peripheral:
    def __init__(self):
        self.is_connected=True;self.mtu_size=23;self.notify=None;self.parts=m.ProxyAssembler()
        self.seq=1000;self.target=76;self.values={'heater_state':0,'filter_state':1,'bubble_state':0,'bubble_level':1,'jet_state':0,'ozone_state':0,'uvc_state':1}
        self.access_sent=[];self.reject=False;self.disconnects=0

    async def start_notify(self,uuid,callback):
        self.notify=callback
        body=b'\0'+m.network_id(NET)+bytes(4)
        beacon=b'\x01'+body+m.cmac(m.beacon_key(NET),body)[:8]
        callback(None,b'\x01'+beacon)

    async def disconnect(self):self.is_connected=False;self.disconnects+=1

    def reply(self,access,*,destination=0xD003,key=APP,source=0x0102):
        base=self.seq
        encrypted=t.upper_encrypt(key,0,base,source,destination,access)
        chunks=[encrypted[i:i+12] for i in range(0,len(encrypted),12)]
        zero=base&0x1FFF;last=len(chunks)-1
        for i,chunk in enumerate(chunks):
            if len(encrypted)<=15:lower=bytes([0x40|t.k4(key)])+encrypted
            else:lower=bytes([0xC0|t.k4(key),(zero>>6)&0x7F,((zero&63)<<2)|(i>>3),((i&7)<<5)|last])+chunk
            packet=t.encode_network(NET,0,self.seq,source,destination,lower,ttl=4)
            self.seq+=1
            self.notify(None,b'\0'+packet)
            if len(encrypted)<=15:break

    def state(self):
        tail=b''.join(attr.to_bytes(2,'little')+bytes([self.values[name]]) for attr,name in p.ATTRIBUTES.items() if name in self.values)
        return bytes.fromhex('d3220920010a')+tail+bytes.fromhex('0801000901')+bytes([self.target])+bytes.fromhex('0a0128ff0100fe0100')

    async def write_gatt_char(self,uuid,data,response=False):
        message=self.parts.feed(data)
        if not message:return
        kind,packet=message
        decoded=t.decode_network(NET,0,packet,proxy=kind==2)
        if kind==2:
            answer=t.encode_network(NET,0,self.seq,0x0102,0,bytes.fromhex('03010000'),proxy=True,ctl=True)
            self.seq+=1;self.notify(None,b'\x02'+answer);return
        if decoded['ctl']:return
        plain=t.upper_decrypt(APP,0,decoded['sequence'],decoded['source'],decoded['destination'],decoded['payload'][1:])
        self.access_sent.append(plain)
        self.reply(bytes.fromhex('d32209')+plain[3:4]+bytes.fromhex('010a00000000'),destination=decoded['source'])
        if plain[6:]==bytes.fromhex('160101'):
            self.reply(self.state())
        elif not self.reject:
            attr=int.from_bytes(plain[6:8],'little');name=p.ATTRIBUTES[attr]
            if name=='temperature_setting':self.target=plain[8]
            else:self.values[name]=plain[8]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seq=0;self.saved=[];self.states=[];self.ble=Peripheral()
        async def reserve(iv):
            self.seq+=1;self.saved.append(self.seq);return self.seq
        self.session=p.MeshSession(PROFILE,reserve,self.states.append,timeout=.15)
        await self.session.open(self.ble)

    async def asyncTearDown(self):await self.session.close()

    async def test_fragmented_read_and_half_degree_set_readback(self):
        state=await self.session.read()
        self.assertEqual(p.temperatures(state)['water_temperature'],20)
        state=await self.session.write({'temperature_setting':p.target_raw(39.5)})
        self.assertEqual(p.temperatures(state)['target_temperature'],39.5)
        self.assertTrue(any(x[6:]==bytes.fromhex('09014f') for x in self.ble.access_sent))
        self.assertEqual(self.ble.values['heater_state'],0)

    async def test_zero_ack_does_not_confirm_rejected_write(self):
        self.ble.reject=True
        with self.assertRaises(TimeoutError):await self.session.write({'temperature_setting':78})

    async def test_wrong_app_key_and_wrong_source_do_not_update(self):
        count=len(self.states)
        self.ble.reply(self.ble.state(),key=bytes(16))
        self.ble.reply(self.ble.state(),source=0x0103)
        await asyncio.sleep(.01)
        self.assertEqual(len(self.states),count)

    async def test_nonce_persistence_failure_prevents_send(self):
        async def failed(iv):raise OSError('synthetic store failure')
        self.session.reserve_sequence=failed
        with self.assertRaises(OSError):await self.session.read()
        self.assertEqual(self.ble.access_sent,[])

    async def test_invalid_values_fail_before_any_write(self):
        with self.assertRaises(ValueError):await self.session.write({'heater_state':1,'temperature_setting':81})
        self.assertEqual(self.ble.access_sent,[])

    async def test_group_status_is_not_segment_acknowledged(self):
        await self.session.read()
        self.assertEqual(self.seq,2)  # filter plus read, no group Segment ACK

    def test_encoding_validation_and_unit_conversion(self):
        self.assertEqual(p.write_attribute('temperature_setting',78).hex(),'d1220900010a09014e')
        for value in (19,40.1,39.25,float('nan'),True):
            with self.assertRaises(ValueError):p.target_raw(value)
        self.assertIsNone(p.decode_status(bytes.fromhex('d3220901010a00000000')))
        self.assertEqual(p.temperatures({'temperature_unit':1,'water_temperature':136}),{})


def stub(name,**values):
    module=ModuleType(name);module.__dict__.update(values);sys.modules[name]=module;return module
stub('homeassistant');stub('homeassistant.components')
bt=stub('homeassistant.components.bluetooth',BluetoothScanningMode=SimpleNamespace(ACTIVE='active'))
stub('homeassistant.core',callback=lambda f:f)
class HAError(Exception):pass
stub('homeassistant.exceptions',HomeAssistantError=HAError)
stub('homeassistant.helpers')
class Store:
    data={};fail=False
    def __init__(self,hass,version,key):self.key=key
    async def async_load(self):return self.data.get(self.key)
    async def async_save(self,data):
        if self.fail:raise OSError('synthetic store failure')
        self.data[self.key]=dict(data)
stub('homeassistant.helpers.storage',Store=Store)
class Coordinator:
    def __init__(self,hass,*args,**kwargs):self.hass=hass;self.data=None;self.last_update_success=True
    def async_set_updated_data(self,data):self.data=data;self.last_update_success=True
    def async_set_update_error(self,error):self.last_update_success=False
class CoordinatorEntity:
    def __init__(self,coordinator):self.coordinator=coordinator
    @property
    def available(self):return self.coordinator.last_update_success
stub('homeassistant.helpers.update_coordinator',DataUpdateCoordinator=Coordinator,UpdateFailed=HAError,CoordinatorEntity=CoordinatorEntity)
stub('homeassistant.util',dt=SimpleNamespace(utcnow=lambda:datetime.now(timezone.utc)))
c=importlib.import_module('local02.coordinator')
cloud=importlib.import_module('local02.cloud')

# Load every HA platform and UI flow so packaging/API wiring is exercised too.
class Entity:pass
stub('homeassistant.helpers.entity',EntityCategory=SimpleNamespace(DIAGNOSTIC='diagnostic'))
stub('homeassistant.helpers.device_registry',DeviceInfo=lambda **kwargs:kwargs)
stub('homeassistant.const',UnitOfTemperature=SimpleNamespace(CELSIUS='°C'),ATTR_TEMPERATURE='temperature')
stub('homeassistant.components.sensor',SensorEntity=Entity,
    SensorDeviceClass=SimpleNamespace(TEMPERATURE='temperature',SIGNAL_STRENGTH='signal',POWER='power',ENERGY='energy'),
    SensorStateClass=SimpleNamespace(MEASUREMENT='measurement',TOTAL_INCREASING='total_increasing'))
stub('homeassistant.components.switch',SwitchEntity=Entity)
stub('homeassistant.components.number',NumberEntity=Entity)
stub('homeassistant.components.binary_sensor',BinarySensorEntity=Entity)
stub('homeassistant.components.button',ButtonEntity=Entity)
from enum import IntFlag
class ClimateFeatures(IntFlag):TARGET_TEMPERATURE=1;TURN_ON=2;TURN_OFF=4
stub('homeassistant.components.climate',ClimateEntity=Entity,ClimateEntityFeature=ClimateFeatures,
    HVACMode=SimpleNamespace(HEAT='heat',OFF='off'),HVACAction=SimpleNamespace(HEATING='heating',IDLE='idle',OFF='off'))
platforms={name:importlib.import_module('local02.'+name) for name in ('sensor','switch','number','binary_sensor','button','climate')}
class FlowBase:
    def __init_subclass__(cls,**kwargs):pass
    def __init__(self):self.hass=SimpleNamespace()
    def async_show_form(self,**kwargs):return {'type':'form',**kwargs}
    def async_show_menu(self,**kwargs):return {'type':'menu',**kwargs}
    def async_create_entry(self,**kwargs):return {'type':'create_entry',**kwargs}
    async def async_set_unique_id(self,uuid):self.unique_id=uuid
    def _abort_if_unique_id_configured(self):pass
stub('homeassistant.config_entries',ConfigFlow=FlowBase,OptionsFlow=FlowBase)
stub('homeassistant.helpers.aiohttp_client',async_get_clientsession=lambda hass:None)
selector=stub('homeassistant.helpers.selector',
    TextSelector=lambda config:lambda value:value,TextSelectorConfig=lambda **kwargs:kwargs,
    TextSelectorType=SimpleNamespace(PASSWORD='password'))
flow=importlib.import_module('local02.config_flow')


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        Store.data={};Store.fail=False
        self.hass=SimpleNamespace(loop=asyncio.get_running_loop())
        self.entry=SimpleNamespace(entry_id='test',data={},options={})
        self.coordinator=c.MSpaCoordinator(self.hass,self.entry,PROFILE)

    async def test_sequence_survives_new_allocator_and_concurrent_calls(self):
        a=c.SequenceAllocator(self.hass,PROFILE,0x7FFD)
        self.assertEqual(await asyncio.gather(*(a.reserve(0) for _ in range(3))),[1,2,3])
        b=c.SequenceAllocator(self.hass,PROFILE,0x7FFD)
        self.assertEqual(await b.reserve(0),4)
        with self.assertRaises(ValueError):await b.reserve(1)

    async def test_failed_store_does_not_advance_reserved_sequence(self):
        a=c.SequenceAllocator(self.hass,PROFILE,0x7FFD);Store.fail=True
        with self.assertRaises(OSError):await a.reserve(0)
        Store.fail=False;self.assertEqual(await a.reserve(0),1)

    async def test_switch_commands_preserve_cloud_dependencies(self):
        writes=[]
        async def write(values):writes.append(values)
        self.coordinator.async_write=write
        self.coordinator.raw={'filter_state':1,'heater_state':0,'bubble_state':0,'bubble_level':0,'temperature_unit':0}
        await self.coordinator.async_set_feature('filter',False)
        await self.coordinator.async_set_feature('bubble',True)
        await self.coordinator.async_set_temperature(39)
        self.assertEqual(writes,[{'heater_state':0,'filter_state':0},{'bubble_level':1,'bubble_state':1},{'temperature_setting':78}])

    async def test_failed_command_marks_entities_unavailable(self):
        async def fail(values=None):raise TimeoutError
        self.coordinator._transaction=fail
        with self.assertRaises(HAError):await self.coordinator.async_write({'heater_state':1})
        self.assertFalse(self.coordinator.last_update_success)

    async def test_shutdown_cancels_active_read_and_disconnects(self):
        ble=Peripheral()
        session=p.MeshSession(PROFILE,self.coordinator.sequence.reserve,lambda s:None,timeout=30)
        session.client=ble
        self.coordinator.session=session
        async def ensure():return session
        self.coordinator._ensure_session=ensure
        task=asyncio.create_task(self.coordinator._transaction())
        await asyncio.sleep(.01)
        await self.coordinator.async_shutdown()
        self.assertTrue(task.cancelled());self.assertEqual(ble.disconnects,1)

    def test_main_account_import_and_private_repr(self):
        export={'mesh_response': {'code': 0, 'data': {'netKeys': [{'key': NET.hex()}],
            'nodes': [{'appKeys': [{'netKey': NET.hex(), 'key': APP.hex()}],
                       'deviceKey': '11'*16, 'deviceUUID': 'synthetic-test-uuid',
                       'unicastAddress': '0102', 'deviceid': 'synthetic-test-device'}]}},
            'devices_response': {'data': {'list': [{'device_id': 'synthetic-test-device',
                'device_alias': 'Test spa', 'product_model': 'Test model'}]}}}
        data=cloud.parse_profiles(export['mesh_response'],export['devices_response'])[0]
        profile=m.Profile.from_dict(data)
        self.assertEqual(profile.unicast_address,0x0102)
        self.assertEqual(len(profile.app_key),16)
        for key in ('net_key','app_key','device_key'):
            self.assertNotIn(data[key],repr(profile))
        self.assertNotIn('token',data);self.assertNotIn('password',data)

    async def test_all_platforms_have_unique_entities_and_core_cloud_controls(self):
        self.hass.data={'mspa_local':{'test':self.coordinator}}
        self.coordinator.raw={'water_temperature':40,'temperature_setting':76,'temperature_unit':0,
            'heater_state':0,'filter_state':1,'bubble_level':1,'heat_state':0,'fault':0,'warning':0}
        self.coordinator.data=self.coordinator._data()
        entities=[]
        for module in platforms.values():await module.async_setup_entry(self.hass,self.entry,lambda values:entities.extend(values))
        ids=[entity._attr_unique_id for entity in entities]
        self.assertEqual(len(ids),len(set(ids)))
        switches=[entity for entity in entities if type(entity).__name__=='MSpaSwitch']
        self.assertEqual({entity.feature for entity in switches},{'heater','filter','bubble','jet','ozone','uvc'})
        climate=next(e for e in entities if type(e).__name__=='MSpaClimate')
        self.assertEqual(climate.current_temperature,20)
        self.assertEqual(climate.target_temperature,38)
        self.assertEqual(climate.hvac_mode,'off')
        self.coordinator.last_update_success=False
        self.assertFalse(climate.available)
        self.assertFalse(any(e._attr_name in ('Heater Power','Total Power','Total Energy') for e in entities))

    async def test_options_keep_keys_and_polling_settings(self):
        f=flow.MSpaLocalOptionsFlow()
        f.config_entry=SimpleNamespace(unique_id=PROFILE.unique_id,
            data={'profile':PROFILE.as_dict()},options={})
        form=await f.async_step_manual()
        user=form['data_schema']({'name':'Edited','model':'Test model','unicast_address_hex':'0102',
            'net_key':'','app_key':'','controller_address_hex':'7FFD','poll_seconds':90,'probe_seconds':60})
        result=await f.async_step_manual(user)
        self.assertEqual(result['type'],'create_entry')
        self.assertEqual(result['data']['profile']['app_key'],APP.hex())
        self.assertNotIn('estimate_power',result['data'])
        self.assertEqual(result['data']['poll_seconds'],90)

    async def test_manual_missing_app_key_and_source_collision_rejected(self):
        f=flow.MSpaLocalConfigFlow()
        form=await f.async_step_manual()
        user=form['data_schema']({'name':'Test','model':'Test','unicast_address_hex':'0102',
            'net_key':NET.hex(),'app_key':'','controller_address_hex':'7FFD'})
        self.assertEqual((await f.async_step_manual(user))['errors']['base'],'invalid_profile')
        user.update(app_key=APP.hex(),controller_address_hex='0102')
        self.assertEqual((await f.async_step_manual(user))['errors']['base'],'invalid_profile')

    async def test_key_or_iv_transition_blocks_access(self):
        session=p.MeshSession(PROFILE,self.coordinator.sequence.reserve,lambda s:None)
        session.beacon_state={'iv_index':1,'iv_update':False,'key_refresh':False}
        with self.assertRaises(ValueError):await session.read()


if __name__=='__main__':unittest.main(verbosity=2)
