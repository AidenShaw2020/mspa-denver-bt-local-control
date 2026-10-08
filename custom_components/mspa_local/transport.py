# SPDX-License-Identifier: Apache-2.0
"""Bluetooth Mesh network encryption for bounded local protocol experiments."""
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM


def cmac(key, data):
    c=CMAC(algorithms.AES(key)); c.update(data); return c.finalize()


def k2(net_key):
    salt=cmac(bytes(16),b'smk2'); t=cmac(salt,net_key)
    t1=cmac(t,b'\0\x01')
    t2=cmac(t,t1+b'\0\x02')
    t3=cmac(t,t2+b'\0\x03')
    return t1[-1]&0x7f,t2,t3


def k4(app_key):
    salt=cmac(bytes(16),b'smk4')
    return cmac(cmac(salt,app_key),b'id6\x01')[-1]&0x3f


def upper_encrypt(key,iv_index,sequence,source,destination,payload,*,device_key=False):
    nonce=bytes([2 if device_key else 1,0])+sequence.to_bytes(3,'big')+source.to_bytes(2,'big')+destination.to_bytes(2,'big')+iv_index.to_bytes(4,'big')
    return AESCCM(key,tag_length=4).encrypt(nonce,payload,None)


def upper_decrypt(key,iv_index,sequence,source,destination,payload,*,device_key=False,aszmic=False):
    nonce=bytes([2 if device_key else 1,0x80 if aszmic else 0])+sequence.to_bytes(3,'big')+source.to_bytes(2,'big')+destination.to_bytes(2,'big')+iv_index.to_bytes(4,'big')
    try: return AESCCM(key,tag_length=8 if aszmic else 4).decrypt(nonce,payload,None)
    except (InvalidTag,ValueError): return None


class AccessAssembler:
    """Collect authenticated network segments; authenticate upper transport later."""
    def __init__(self): self.messages={}

    def feed(self,decoded):
        data=decoded['payload']
        if decoded['ctl'] or not data: return None
        if not data[0]&0x80:
            return {'akf':bool(data[0]&0x40),'aid':data[0]&0x3f,'aszmic':False,
                    'sequence':decoded['sequence'],'source':decoded['source'],
                    'destination':decoded['destination'],'encrypted':data[1:],'ack':None}
        if len(data)<5: return None
        zero=((data[1]&0x7f)<<6)|(data[2]>>2)
        index=((data[2]&3)<<3)|(data[3]>>5); last=data[3]&31
        if index>last or len(data[4:])>12 or (index<last and len(data[4:])!=12): return None
        sequence=(decoded['sequence']&~0x1fff)|zero
        if sequence>decoded['sequence']: sequence-=0x2000
        if sequence<0: return None
        key=(decoded['source'],decoded['destination'],sequence,data[0]&0x7f,data[1]&0x80,last)
        if key not in self.messages:
            if len(self.messages)>=16:self.messages.clear()
            self.messages[key]={}
        parts=self.messages[key]
        if index in parts and parts[index]!=data[4:]:
            self.messages.pop(key); return None
        parts[index]=data[4:]
        if len(parts)!=last+1:return None
        encrypted=b''.join(parts[i] for i in range(last+1))
        self.messages.pop(key)
        return {'akf':bool(data[0]&0x40),'aid':data[0]&0x3f,'aszmic':bool(data[1]&0x80),
                'sequence':sequence,'source':decoded['source'],'destination':decoded['destination'],
                'encrypted':encrypted,'ack':b'\0'+(zero<<2).to_bytes(2,'big')+((1<<(last+1))-1).to_bytes(4,'big')}


def aes(key,block):
    e=Cipher(algorithms.AES(key),modes.ECB()).encryptor()
    return e.update(block)+e.finalize()


def encode_network(net_key,iv_index,sequence,source,destination,payload,*,proxy=False,ctl=False,ttl=0):
    if not (0<=iv_index<=0xffffffff and 0<=sequence<=0xffffff and
            1<=source<=0x7fff and 0<=destination<=0xffff and 0<=ttl<=127):
        raise ValueError('Invalid Mesh network fields')
    if proxy and (not ctl or ttl or destination):
        raise ValueError('Invalid Proxy Configuration fields')
    nid,encryption,privacy=k2(net_key)
    ctl_ttl=(0x80 if ctl else 0)|ttl
    seq=sequence.to_bytes(3,'big'); src=source.to_bytes(2,'big'); iv=iv_index.to_bytes(4,'big')
    nonce=bytes([3 if proxy else 0,0 if proxy else ctl_ttl])+seq+src+bytes(2)+iv
    encrypted=AESCCM(encryption,tag_length=8 if ctl else 4).encrypt(
        nonce,destination.to_bytes(2,'big')+payload,None)
    pecb=aes(privacy,bytes(5)+iv+encrypted[:7])[:6]
    header=bytes([ctl_ttl])+seq+src
    obfuscated=bytes(x^y for x,y in zip(header,pecb))
    return bytes([((iv_index&1)<<7)|nid])+obfuscated+encrypted


def decode_network(net_key,iv_index,packet,*,proxy=False):
    if len(packet)<14: return None
    nid,encryption,privacy=k2(net_key)
    if packet[0] != ((iv_index&1)<<7)|nid: return None
    iv=iv_index.to_bytes(4,'big'); encrypted=packet[7:]
    pecb=aes(privacy,bytes(5)+iv+encrypted[:7])[:6]
    header=bytes(x^y for x,y in zip(packet[1:7],pecb))
    ctl_ttl=header[0]; ctl=bool(ctl_ttl&0x80)
    seq=header[1:4]; src=header[4:6]
    if not 1<=int.from_bytes(src,'big')<=0x7fff: return None
    if proxy and ctl_ttl!=0x80: return None
    nonce=bytes([3 if proxy else 0,0 if proxy else ctl_ttl])+seq+src+bytes(2)+iv
    try:
        plain=AESCCM(encryption,tag_length=8 if ctl else 4).decrypt(nonce,encrypted,None)
    except (InvalidTag,ValueError): return None
    if len(plain)<2: return None
    dst=int.from_bytes(plain[:2],'big')
    if proxy and dst: return None
    return {'source':int.from_bytes(src,'big'),'destination':dst,
            'sequence':int.from_bytes(seq,'big'),'ctl':ctl,'ttl':ctl_ttl&0x7f,
            'payload':plain[2:]}
