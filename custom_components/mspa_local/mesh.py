# SPDX-License-Identifier: Apache-2.0
"""Bluetooth Mesh identification and authenticated beacons, independent of HA."""
from dataclasses import dataclass, field
import hmac
import json
from pathlib import Path

from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PROXY_SERVICE = "00001828-0000-1000-8000-00805f9b34fb"
PROXY_IN = "00002add-0000-1000-8000-00805f9b34fb"
PROXY_OUT = "00002ade-0000-1000-8000-00805f9b34fb"


def cmac(key: bytes, data: bytes) -> bytes:
    context = CMAC(algorithms.AES(key))
    context.update(data)
    return context.finalize()


def s1(data: bytes) -> bytes:
    return cmac(bytes(16), data)


def k1(key: bytes, salt: bytes, info: bytes) -> bytes:
    return cmac(cmac(salt, key), info)


def network_id(net_key: bytes) -> bytes:
    return k1(net_key, s1(b"smk3"), b"id64\x01")[-8:]


def identity_key(net_key: bytes) -> bytes:
    return k1(net_key, s1(b"nkik"), b"id128\x01")


def beacon_key(net_key: bytes) -> bytes:
    return k1(net_key, s1(b"nkbk"), b"id128\x01")


def node_identity_hash(net_key: bytes, random: bytes, address: int) -> bytes:
    if len(random) != 8 or not 1 <= address <= 0x7FFF:
        raise ValueError("Invalid Node Identity fields")
    encryptor = Cipher(algorithms.AES(identity_key(net_key)), modes.ECB()).encryptor()
    block = bytes(6) + random + address.to_bytes(2, "big")
    return (encryptor.update(block) + encryptor.finalize())[-8:]


@dataclass(frozen=True)
class Profile:
    name: str
    model: str
    device_uuid: str
    unicast_address: int
    net_key: bytes = field(repr=False)
    app_key: bytes = field(default=b'', repr=False)
    device_key: bytes = field(default=b'', repr=False)
    wifi_version: str = ''
    mcu_version: str = ''

    @classmethod
    def load(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("Missing or invalid mspa_profile.json") from None

    @classmethod
    def from_dict(cls, data):
        try:
            key = bytes.fromhex(data["net_key"])
            address = int(data["unicast_address_hex"], 16)
            app_key = bytes.fromhex(data.get('app_key', ''))
            device_key = bytes.fromhex(data.get('device_key', ''))
            if len(app_key) not in (0, 16) or len(device_key) not in (0, 16):
                raise ValueError
            if len(key) != 16 or not 1 <= address <= 0x7FFF:
                raise ValueError
            if any(not isinstance(data.get(item), str) or not data[item]
                   for item in ("model", "device_uuid")):
                raise ValueError
            if "name" in data and not isinstance(data["name"], str):
                raise ValueError
            return cls(data.get("name", "MSpa Denver"), data["model"],
                       data["device_uuid"], address, key, app_key, device_key,
                       str(data.get('wifi_version', '')), str(data.get('mcu_version', '')))
        except (ValueError, KeyError, TypeError):
            # Never include profile contents or keys in error messages.
            raise ValueError("Missing or invalid mspa_profile.json") from None

    @property
    def unique_id(self):
        return self.device_uuid

    def as_dict(self):
        return {"name": self.name, "model": self.model, "device_uuid": self.device_uuid,
                "unicast_address_hex": f"{self.unicast_address:04X}", "net_key": self.net_key.hex(),
                'app_key':self.app_key.hex(), 'device_key':self.device_key.hex(),
                'wifi_version':self.wifi_version, 'mcu_version':self.mcu_version}

    def match_proxy(self, data: bytes) -> str | None:
        if len(data) == 9 and data[0] == 0:
            if hmac.compare_digest(data[1:], network_id(self.net_key)):
                # Network ID identifies a subnet, not an individual node.
                return "network_id"
        elif len(data) == 17 and data[0] == 1:
            expected = node_identity_hash(self.net_key, data[9:17], self.unicast_address)
            if hmac.compare_digest(data[1:9], expected):
                return "node_identity"
        return None

    def verify_beacon(self, data: bytes) -> dict | None:
        if len(data) != 22 or data[0] != 1 or data[1] & 0xFC:
            return None
        if not hmac.compare_digest(data[2:10], network_id(self.net_key)):
            return None
        expected = cmac(beacon_key(self.net_key), data[1:14])[:8]
        if not hmac.compare_digest(data[14:22], expected):
            return None
        return {"iv_index": int.from_bytes(data[10:14], "big"),
                "iv_update": bool(data[1] & 2), "key_refresh": bool(data[1] & 1)}


class ProxyAssembler:
    """Reassemble one GATT Proxy message with strict type/SAR and size checks."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.kind = None
        self.parts = bytearray()

    def feed(self, packet: bytes) -> tuple[int, bytes] | None:
        if not packet:
            self.reset()
            return None
        sar, kind = packet[0] >> 6, packet[0] & 0x3F
        if kind > 3:
            self.reset()
            return None
        if sar == 0:
            self.reset()
            return (kind, packet[1:]) if len(packet) <= 385 else None
        if sar == 1:
            self.kind = kind
            self.parts = bytearray(packet[1:])
        elif self.kind == kind:
            self.parts.extend(packet[1:])
        else:
            self.reset()
            return None
        if len(self.parts) > 384:
            self.reset()
            return None
        if sar == 3:
            message = kind, bytes(self.parts)
            self.reset()
            return message
        return None
