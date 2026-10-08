# SPDX-License-Identifier: Apache-2.0
"""MSpa Link attributes and authenticated Mesh Proxy sessions, independent of HA."""
import asyncio
from collections import deque
import math

from .mesh import PROXY_IN, PROXY_OUT, ProxyAssembler
from . import transport

ATTRIBUTES = {
    0x0101:'heater_state', 0x0102:'filter_state', 0x0103:'bubble_state',
    0x0104:'bubble_level', 0x0105:'ozone_state', 0x0106:'uvc_state',
    0x0107:'jet_state', 0x0108:'temperature_unit', 0x0109:'temperature_setting',
    0x010A:'water_temperature', 0x010B:'auto_inflate', 0x020C:'filter_current',
    0x010D:'heat_time', 0x010E:'safety_lock', 0x0E0F:'serial_number',
    0x0110:'heat_time_switch', 0x0111:'heat_state', 0x0112:'filter_life',
    0x0413:'heat_rest_time', 0x0114:'reset_cloud_time',
    0x0415:'device_heat_perhour', 0x01FE:'warning', 0x01FF:'fault',
}
WRITABLE = {name:attr for attr,name in ATTRIBUTES.items() if name in (
    'heater_state','filter_state','bubble_state','bubble_level','jet_state',
    'ozone_state','uvc_state','temperature_setting')}
FULL_STATUS_READ = bytes.fromhex('d1220900010a160101')


def decode_status(access):
    if len(access)<8 or access[:3]!=bytes.fromhex('d32209') or access[4:6]!=bytes.fromhex('010a'):
        return None
    result={}; offset=6
    while offset<len(access):
        if offset+2>len(access):return None
        attr=int.from_bytes(access[offset:offset+2],'little')&0x7FFF
        length=attr>>8; name=ATTRIBUTES.get(attr)
        if name is None or offset+2+length>len(access):return None
        value=access[offset+2:offset+2+length]
        result[name]=value.decode('ascii',errors='replace') if name=='serial_number' else int.from_bytes(value,'little')
        offset+=2+length
    return result


def target_raw(celsius):
    if isinstance(celsius,bool):raise ValueError('Invalid temperature')
    number=float(celsius)
    if not math.isfinite(number) or not 20<=number<=40 or not (number*2).is_integer():
        raise ValueError('Temperature must be 20–40 Celsius in half-degree steps')
    return int(number*2)


def write_attribute(name,value):
    if name not in WRITABLE or not isinstance(value,int):raise ValueError('Invalid writable attribute')
    if name=='temperature_setting':valid=40<=value<=80
    elif name=='bubble_level':valid=1<=value<=3
    else:valid=value in (0,1)
    if not valid:raise ValueError('Invalid attribute value')
    return bytes.fromhex('d1220900010a')+WRITABLE[name].to_bytes(2,'little')+bytes([value])


def temperatures(state):
    """The verified Celsius protocol uses half-degree values."""
    unit=state.get('temperature_unit')
    if unit!=0:return {}
    result={}
    for raw,key in [('water_temperature','water_temperature'),('temperature_setting','target_temperature')]:
        if raw in state:
            value=state[raw]/2
            result[key]=value
    return result


class MeshSession:
    def __init__(self,profile,reserve_sequence,on_status,*,source=0x7FFD,timeout=40):
        if len(profile.app_key)!=16:raise ValueError('AppKey import required')
        self.profile=profile; self.reserve_sequence=reserve_sequence; self.on_status=on_status
        self.source=source; self.timeout=timeout; self.client=None; self.iv=0
        self.proxy=ProxyAssembler(); self.access=transport.AccessAssembler()
        self.beacon=asyncio.Event(); self.filter=asyncio.Event(); self.closed=False
        self.waiter=None; self.expected={}; self.seen=set(); self.seen_order=deque()
        self.ack_waiters={}; self.tasks=set(); self.loop=asyncio.get_running_loop()
        self.send_lock=asyncio.Lock()
        self.last_state={}; self.beacon_state=None

    async def open(self,client):
        self.client=client
        await client.start_notify(PROXY_OUT,self.notification)
        await asyncio.wait_for(self.beacon.wait(),10)
        if self.beacon_state['iv_index']!=0 or self.beacon_state['iv_update'] or self.beacon_state['key_refresh']:
            raise ValueError('Mesh IV/key migration is not implemented in this test version')
        await self._send_network(b'\x00\x01',proxy=True)
        await asyncio.wait_for(self.filter.wait(),8)

    def notification(self,sender,value):
        self.loop.call_soon_threadsafe(self.feed,bytes(value))

    def feed(self,value):
        if self.closed:return
        message=self.proxy.feed(value)
        if not message:return
        kind,packet=message
        if kind==1:
            verified=self.profile.verify_beacon(packet)
            if verified:self.beacon_state=verified;self.beacon.set()
            return
        if kind not in (0,2):return
        decoded=transport.decode_network(self.profile.net_key,self.iv,packet,proxy=kind==2)
        if decoded is None:return
        if kind==2:
            if decoded['payload']==bytes.fromhex('03010000'):self.filter.set()
            return
        assembled=self.access.feed(decoded)
        if not assembled or not assembled['akf'] or assembled['source']!=self.profile.unicast_address:return
        if assembled['destination'] not in (self.source,0xD003):return
        if assembled['aid']!=transport.k4(self.profile.app_key):return
        plain=transport.upper_decrypt(self.profile.app_key,self.iv,assembled['sequence'],assembled['source'],
            assembled['destination'],assembled['encrypted'],aszmic=assembled['aszmic'])
        if plain is None:return
        if assembled['ack'] is not None and assembled['destination']==self.source:
            task=self.loop.create_task(self._send_network(assembled['ack'],ctl=True))
            self.tasks.add(task);task.add_done_callback(self._ack_finished)
        identity=(assembled['source'],assembled['destination'],assembled['sequence'])
        if identity in self.seen:return
        self.seen.add(identity);self.seen_order.append(identity)
        if len(self.seen_order)>512:self.seen.discard(self.seen_order.popleft())
        if plain[:3]==bytes.fromhex('d32209') and len(plain)>=10 and plain[4:]==bytes.fromhex('010a00000000'):
            event=self.ack_waiters.get(plain[3])
            if event:event.set()
        state=decode_status(plain)
        if state is None:return
        self.last_state.update(state)
        self.on_status(dict(self.last_state))
        # A partial notification cannot turn a cached value into a verified read.
        full=all(k in state for k in ('temperature_unit','water_temperature','temperature_setting'))
        if full and self.waiter and not self.waiter.done() and all(state.get(k)==v for k,v in self.expected.items()):
            self.waiter.set_result(dict(self.last_state))

    def _ack_finished(self,task):
        self.tasks.discard(task)
        if not task.cancelled():task.exception()

    async def _send_proxy(self,kind,packet):
        async with self.send_lock:
            await self._send_proxy_locked(kind,packet)

    async def _send_proxy_locked(self,kind,packet):
        if self.closed or self.client is None or not self.client.is_connected:raise ConnectionError('BLE disconnected')
        mtu=getattr(self.client,'mtu_size',23)
        size=max(19,mtu-4)
        parts=[packet[i:i+size] for i in range(0,len(packet),size)]
        for i,part in enumerate(parts):
            sar=0 if len(parts)==1 else 1 if i==0 else 3 if i==len(parts)-1 else 2
            await self.client.write_gatt_char(PROXY_IN,bytes([(sar<<6)|kind])+part,response=False)
            await asyncio.sleep(0.04)

    async def _send_network(self,payload,*,proxy=False,ctl=False):
        seq=await self.reserve_sequence(self.iv)
        packet=transport.encode_network(self.profile.net_key,self.iv,seq,self.source,
            0 if proxy else self.profile.unicast_address,payload,proxy=proxy,ctl=proxy or ctl,ttl=0 if proxy else 5)
        await self._send_proxy(2 if proxy else 0,packet)

    async def _send_access(self,payload,*,wait_ack=False):
        if self.beacon_state and (self.beacon_state['iv_index']!=0 or self.beacon_state['iv_update'] or self.beacon_state['key_refresh']):
            raise ValueError('Mesh IV/key migration is required')
        seq=await self.reserve_sequence(self.iv); tid=(seq%254)+1
        payload=payload[:3]+bytes([tid])+payload[4:]
        upper=transport.upper_encrypt(self.profile.app_key,self.iv,seq,self.source,self.profile.unicast_address,payload)
        if len(upper)>15:raise ValueError('Outgoing segmented access is not supported')
        packet=transport.encode_network(self.profile.net_key,self.iv,seq,self.source,self.profile.unicast_address,
            bytes([0x40|transport.k4(self.profile.app_key)])+upper,ttl=5)
        event=asyncio.Event()
        if wait_ack:self.ack_waiters[tid]=event
        try:
            await self._send_proxy(0,packet)
            if wait_ack:
                try:await asyncio.wait_for(event.wait(),5)
                except TimeoutError:pass  # Only read-back can confirm a write.
        finally:self.ack_waiters.pop(tid,None)

    async def read(self,expected=None):
        if self.waiter is not None:raise RuntimeError('Concurrent Mesh request')
        self.expected=dict(expected or {}); self.waiter=self.loop.create_future()
        waiter=self.waiter
        try:
            await self._send_access(FULL_STATUS_READ)
            return await asyncio.wait_for(self.waiter,self.timeout)
        finally:
            if not waiter.done():waiter.cancel()
            elif not waiter.cancelled():waiter.exception()
            self.waiter=None;self.expected={}

    async def write(self,values):
        # Validate every value before sending anything. Each TLV fits unsegmented.
        payloads=[write_attribute(k,v) for k,v in values.items()]
        for payload in payloads:await self._send_access(payload,wait_ack=True)
        return await self.read(values)

    def disconnected(self):
        self.closed=True
        if self.waiter and not self.waiter.done():self.waiter.set_exception(ConnectionError('BLE disconnected'))

    async def close(self):
        self.disconnected()
        tasks=list(self.tasks)
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        if self.client:
            try:await asyncio.wait_for(self.client.disconnect(),10)
            except Exception:pass
