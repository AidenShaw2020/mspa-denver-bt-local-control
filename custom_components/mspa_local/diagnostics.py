# SPDX-License-Identifier: Apache-2.0
"""Allow-list diagnostics; never return config entries, keys or login tokens."""
from .const import DOMAIN, VERSION


async def async_get_config_entry_diagnostics(hass,entry):
    c=hass.data[DOMAIN][entry.entry_id]
    return {'version':VERSION,'model':c.profile.model,'source':f'{c.source:04X}',
        'unicast_address':f'{c.profile.unicast_address:04X}','last_seen':c.last_seen,
        'last_update_success':c.last_update_success,
        'connection':{k:v for k,v in c.diagnostic.items() if k not in ('address','advertisement_source')},
        'state':{k:v for k,v in c.raw.items() if k!='serial_number'}}
