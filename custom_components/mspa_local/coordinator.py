# SPDX-License-Identifier: Apache-2.0
"""Serialized Bluetooth Mesh I/O through HA's shared BLE manager."""
import asyncio
from datetime import timedelta
import logging
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from .const import DOMAIN, POLL_SECONDS, PROBE_SECONDS, CONTROLLER_ADDRESS, FEATURES
from .mesh import PROXY_SERVICE, network_id
from .protocol import MeshSession, target_raw, temperatures

_LOGGER=logging.getLogger(__name__)


class SequenceAllocator:
    """Persist a reserved nonce before any encrypted packet is sent."""
    def __init__(self,hass,profile,source):
        self.source=source;self.identity=network_id(profile.net_key).hex()
        self.store=Store(hass,1,f'{DOMAIN}.sequence.{self.identity}.{source:04x}')
        self.state=None;self.lock=asyncio.Lock()

    async def reserve(self,iv):
        async with self.lock:
            if self.state is None:
                saved=await self.store.async_load()
                self.state=saved if saved is not None else {
                    'source':self.source,'network_id':self.identity,'iv_index':iv,'next_sequence':1}
            state=self.state
            if not isinstance(state,dict) or state.get('source')!=self.source or state.get('network_id')!=self.identity or state.get('iv_index')!=iv:
                raise ValueError('Invalid sequence state or unsupported IV migration')
            seq=state.get('next_sequence')
            if not isinstance(seq,int) or isinstance(seq,bool) or not 1<=seq<0xFFFFFF:
                raise ValueError('Mesh sequence exhausted or invalid')
            updated={**state,'next_sequence':seq+1}
            await self.store.async_save(updated)
            self.state=updated
            return seq


class MSpaCoordinator(DataUpdateCoordinator):
    def __init__(self,hass,entry,profile):
        options={**entry.data,**entry.options}
        self.settings=options
        super().__init__(hass,_LOGGER,name='MSpa Local',config_entry=entry,
            update_interval=timedelta(seconds=options.get('poll_seconds',POLL_SECONDS)))
        self.entry=entry;self.profile=profile
        self.timeout=options.get('probe_seconds',PROBE_SECONDS)
        self.source=int(options.get('controller_address_hex',CONTROLLER_ADDRESS),16)
        if not 1<=self.source<=0x7FFF or self.source==profile.unicast_address:
            raise ValueError('Invalid Mesh controller source address')
        self.sequence=SequenceAllocator(hass,profile,self.source)
        self.candidates={};self.discovery=asyncio.Event();self.session=None
        self.lock=asyncio.Lock();self.stopping=False;self.operation=None
        self.raw={};self.last_seen=None
        self.diagnostic={'status':'waiting_for_proxy','address':None,'rssi':None,
            'advertisement_source':None,'identity_match':None,'iv_index':None,
            'netkey_verified':False,'appkey_verified':False,'last_error_type':None}

    @callback
    def start_discovery(self):
        self.entry.async_on_unload(bluetooth.async_register_callback(
            self.hass,self._discovered,{'service_uuid':PROXY_SERVICE,'connectable':True},
            bluetooth.BluetoothScanningMode.ACTIVE))
        for info in bluetooth.async_discovered_service_info(self.hass,connectable=True):
            self._discovered(info,None)

    @callback
    def _discovered(self,info,change):
        data=next((v for k,v in info.service_data.items() if k.lower()==PROXY_SERVICE),None)
        if data is None:return
        kind=self.profile.match_proxy(bytes(data))
        if kind:
            self.candidates[info.address]={'identity_match':kind,'rssi':info.rssi,
                'advertisement_source':info.source}
            self.discovery.set()

    def _status_received(self,raw):
        self.raw=dict(raw)
        if self.last_update_success and self.data and not self.stopping:
            self.async_set_updated_data(self._data())

    def _data(self):
        data={'raw':dict(self.raw),**temperatures(self.raw),
                'last_seen':self.last_seen,'diagnostic':dict(self.diagnostic)}
        return data

    async def _ensure_session(self):
        if self.session and not self.session.closed and self.session.client.is_connected:
            return self.session
        await self._close_session()
        if not self.candidates:
            self.discovery.clear()
            await asyncio.wait_for(self.discovery.wait(),25)
        available={address:candidate for address,candidate in self.candidates.items()
            if bluetooth.async_ble_device_from_address(self.hass,address,connectable=True) is not None}
        if not available:raise ConnectionError('No matching connectable MSpa Mesh proxy')
        address=max(available,key=lambda a:(available[a]['identity_match']=='node_identity',available[a]['rssi']))
        self.diagnostic.update(available[address]);self.diagnostic['address']=address
        self.diagnostic['status']='connecting'
        device=bluetooth.async_ble_device_from_address(self.hass,address,connectable=True)
        session=MeshSession(self.profile,self.sequence.reserve,self._status_received,
                            source=self.source,timeout=self.timeout)
        self.session=session
        def disconnected(client):
            self.hass.loop.call_soon_threadsafe(session.disconnected)
        async with asyncio.timeout(45):
            client=await establish_connection(BleakClientWithServiceCache,device,'MSpa Local',
                max_attempts=2,disconnected_callback=disconnected,
                ble_device_callback=lambda:bluetooth.async_ble_device_from_address(self.hass,address,connectable=True))
            session.client=client
            if client.services.get_service(PROXY_SERVICE) is None:raise ValueError('Missing Mesh Proxy GATT service')
            await session.open(client)
        self.diagnostic.update(status='connected',netkey_verified=True,iv_index=session.iv)
        return session

    async def _close_session(self):
        if self.session:
            session=self.session;self.session=None
            await session.close()

    async def _transaction(self,values=None):
        async with self.lock:
            if self.stopping:raise ConnectionError('Integration stopping')
            self.operation=asyncio.current_task()
            try:
                session=await self._ensure_session()
                raw=await (session.read() if values is None else session.write(values))
                self.raw=raw;self.last_seen=dt_util.utcnow().isoformat()
                self.diagnostic.update(status='state_verified',appkey_verified=True,last_error_type=None)
                return self._data()
            except asyncio.CancelledError:
                await self._close_session();raise
            except Exception as error:
                self.diagnostic.update(status='connection_failed',last_error_type=type(error).__name__)
                await self._close_session()
                raise
            finally:self.operation=None

    async def _async_update_data(self):
        try:return await self._transaction()
        except Exception as error:
            raise UpdateFailed(f'Bluetooth state read failed ({type(error).__name__})') from None

    async def async_write(self,values):
        try:data=await self._transaction(values)
        except Exception as error:
            self.async_set_update_error(UpdateFailed(type(error).__name__))
            raise HomeAssistantError('MSpa did not confirm the requested state over Bluetooth') from None
        self.async_set_updated_data(data)

    async def async_set_temperature(self,value):
        if self.raw.get('temperature_unit')!=0:
            raise HomeAssistantError('Set Celsius in the MSpa app before changing target temperature')
        try:raw=target_raw(value)
        except (ValueError,TypeError):raise HomeAssistantError('Use 20–40 Celsius in 0.5 degree steps') from None
        await self.async_write({'temperature_setting':raw})

    async def async_set_feature(self,feature,is_on):
        if feature not in FEATURES:raise HomeAssistantError('Unknown MSpa feature')
        key=FEATURES[feature][1]
        if key not in self.raw:raise HomeAssistantError('Feature not reported by this device')
        values={}
        if feature=='filter' and not is_on:values['heater_state']=0
        if feature=='bubble' and is_on:
            level=self.raw.get('bubble_level',1)
            values['bubble_level']=level if level in (1,2,3) else 1
        values[key]=int(is_on)
        await self.async_write(values)

    async def async_set_bubble_level(self,level):
        if isinstance(level,bool) or level not in (1,2,3):raise HomeAssistantError('Bubble level must be 1, 2 or 3')
        await self.async_write({'bubble_level':int(level)})

    async def async_probe(self):
        data=await self._transaction();self.async_set_updated_data(data)

    async def async_shutdown(self):
        self.stopping=True
        if self.operation and self.operation is not asyncio.current_task():
            self.operation.cancel()
            try:await self.operation
            except (asyncio.CancelledError,Exception):pass
        await self._close_session()
