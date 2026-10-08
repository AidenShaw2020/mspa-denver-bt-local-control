# SPDX-License-Identifier: Apache-2.0
"""Configuration-only Mesh import. Authentication adapted from DTekNO/mspa-homeassistant.

Modified from upstream: asynchronous HTTP transport, configuration-only Mesh
key import, node-bound key selection, and credential handling.

Apache-2.0; commit bdaa2420e34dee1c7449873d79eb7b17691a3426. See LICENSE/NOTICE.
"""
import asyncio
import hashlib
import json
import secrets
import time
import aiohttp
from .mesh import Profile

APP_ID = "e1c8e068f9ca11eba4dc0242ac120002"
APP_SECRET = "87025c9ecd18906d27225fe79cb68349"
ENDPOINTS = {"ROW": "https://api.iot.the-mspa.com", "US": "https://api.usiot.the-mspa.com",
             "CH": "https://api.mspa.mxchip.com.cn"}


class CloudError(Exception):
    """Safe translatable error code; no server responses or credentials."""


def md5(value):
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


def headers(token=""):
    nonce, timestamp = secrets.token_hex(16), str(int(time.time()))
    return {"appid": APP_ID, "nonce": nonce, "ts": timestamp,
            "sign": md5(f"{APP_ID},{APP_SECRET},{nonce},{timestamp}").upper(),
            "authorization": f"token {token}" if token else "token",
            "push_type": "Android", "lan_code": "de"}


def parse_profiles(mesh_response, devices_response):
    data = mesh_response.get("data")
    if isinstance(data, str):
        try: data = json.loads(data)
        except ValueError: raise CloudError("invalid_mesh") from None
    if mesh_response.get("code") not in (None, 0, "0") or not isinstance(data, dict):
        raise CloudError("invalid_mesh")
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes: raise CloudError("no_mesh_nodes")
    nets = data.get("netKeys", [])
    if not isinstance(nets, list): raise CloudError("invalid_mesh")
    networks = {n["key"].lower() for n in nets
                if isinstance(n, dict) and isinstance(n.get("key"), str)}
    device_data = devices_response.get("data", {})
    device_list = device_data.get("list", []) if isinstance(device_data, dict) else []
    if not isinstance(device_list, list): device_list = []
    devices = {d.get("device_id"): d for d in device_list if isinstance(d, dict)}
    profiles, seen = [], set()
    for node in nodes:
        if not isinstance(node, dict): continue
        bindings = node.get("appKeys", [])
        if not isinstance(bindings, list): continue
        keys = {b["netKey"].lower() for b in bindings if isinstance(b, dict)
                and isinstance(b.get("netKey"), str) and b["netKey"].lower() in networks}
        if len(keys) != 1: continue
        network_key = keys.pop()
        app_keys = {b.get('key', '').lower() for b in bindings if isinstance(b, dict)
                    and isinstance(b.get('key'), str) and isinstance(b.get('netKey'), str)
                    and b['netKey'].lower() == network_key}
        if len(app_keys) != 1: continue
        device = devices.get(node.get("deviceid"), {})
        profile_data = {"name": device.get("device_alias") or node.get("name") or "MSpa",
            "model": device.get("product_model") or "MSpa",
            "device_uuid": node.get("deviceUUID") or node.get("UUID"),
            "unicast_address_hex": node.get("unicastAddress"), "net_key": network_key,
            'app_key':app_keys.pop(), 'device_key':node.get('deviceKey', ''),
            'wifi_version':device.get('wifi_version', ''), 'mcu_version':device.get('mcu_version', '')}
        try: profile = Profile.from_dict(profile_data)
        except ValueError: continue
        if len(profile.app_key) != 16: continue
        if profile.unique_id not in seen:
            profiles.append(profile.as_dict()); seen.add(profile.unique_id)
    if not profiles: raise CloudError("invalid_mesh")
    return profiles


async def async_fetch_profiles(session, email, password, region):
    base = ENDPOINTS[region]
    async def request(method, path, payload=None, token=""):
        try:
            async with session.request(method, base+path, json=payload, headers=headers(token),
                    allow_redirects=False, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status in (401, 403): raise CloudError("invalid_auth")
                if response.status != 200: raise CloudError("cannot_connect")
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body)>8*1024*1024: raise CloudError("invalid_mesh")
                result = json.loads(body.decode("utf-8-sig"))
                if not isinstance(result, dict): raise CloudError("invalid_mesh")
                return result
        except (aiohttp.ClientError, TimeoutError, OSError):
            raise CloudError("cannot_connect") from None
        except (ValueError, UnicodeError):
            raise CloudError("invalid_mesh") from None
    login = await request("POST", "/api/enduser/get_token/", {
        "account": email.strip(), "app_id": APP_ID, "password": md5(password.strip()),
        "brand": "", "registration_id": "", "push_type": "android", "lan_code": "EN", "country": ""})
    data = login.get("data")
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token.strip(): raise CloudError("invalid_auth")
    await asyncio.sleep(0.5)
    devices = await request("GET", "/api/enduser/devices/", token=token)
    await asyncio.sleep(0.5)
    mesh = await request("POST", "/api/mesh/network", {"is_default":True}, token)
    return parse_profiles(mesh, devices)
