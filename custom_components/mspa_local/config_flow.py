# SPDX-License-Identifier: Apache-2.0
"""UI account import, device selection and editable local connection settings."""
from uuid import uuid4
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
import voluptuous as vol
from .cloud import CloudError, ENDPOINTS, async_fetch_profiles
from .const import DOMAIN, POLL_SECONDS, CONTROLLER_ADDRESS
from .mesh import Profile

PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


class SettingsSteps:
    is_options = False

    def __init__(self):
        super().__init__()
        self._profiles = []
        self._pending = None
        self._manual_uuid = str(uuid4())

    def existing(self):
        if self.is_options:
            return self.config_entry.options.get("profile", self.config_entry.data["profile"])
        return None

    async def async_step_login(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._profiles = await async_fetch_profiles(async_get_clientsession(self.hass),
                    user_input["email"], user_input["password"], user_input["region"])
                if self.is_options:
                    self._profiles = [p for p in self._profiles
                                      if p["device_uuid"] == self.config_entry.unique_id]
                    if not self._profiles: raise CloudError("device_missing")
                return await self.async_step_select_device()
            except CloudError as error:
                errors["base"] = error.args[0]
        return self.async_show_form(step_id="login", errors=errors, data_schema=vol.Schema({
            vol.Required("email"): str,
            vol.Required("password"): PASSWORD,
            vol.Required("region", default="ROW"): vol.In(ENDPOINTS),
        }))

    async def async_step_select_device(self, user_input=None):
        choices = {p["device_uuid"]: f'{p["name"]} ({p["model"]}, 0x{p["unicast_address_hex"]})'
                   for p in self._profiles}
        if user_input is not None:
            self._pending = next(p for p in self._profiles if p["device_uuid"] == user_input["device"])
            self._profiles = []
            return await self.async_step_manual()
        return self.async_show_form(step_id="select_device", data_schema=vol.Schema({
            vol.Required("device"): vol.In(choices)}))

    async def async_step_manual(self, user_input=None):
        previous = self._pending or self.existing() or {}
        errors = {}
        if user_input is not None:
            profile_data = {
                "name":user_input["name"], "model":user_input["model"],
                "device_uuid":previous.get("device_uuid", self._manual_uuid),
                "unicast_address_hex":user_input["unicast_address_hex"].strip(),
                "net_key":user_input.get("net_key", "").strip() or previous.get("net_key", ""),
                'app_key':user_input.get('app_key','').strip() or previous.get('app_key',''),
                'device_key':previous.get('device_key',''),
                'wifi_version':previous.get('wifi_version',''), 'mcu_version':previous.get('mcu_version',''),
            }
            try:
                profile = Profile.from_dict(profile_data)
                source=int(user_input['controller_address_hex'].strip(),16)
                if len(profile.app_key)!=16 or not 1<=source<=0x7FFF or source==profile.unicast_address:
                    raise ValueError
            except ValueError:
                errors["base"] = "invalid_profile"
            else:
                result = {"profile":profile.as_dict(), "probe_seconds":user_input["probe_seconds"],
                    'poll_seconds':user_input['poll_seconds'],'controller_address_hex':f'{source:04X}'}
                if self.is_options:result={**self.config_entry.options,**result}
                self._pending = None
                if self.is_options:
                    return self.async_create_entry(title="", data=result)
                await self.async_set_unique_id(profile.unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=profile.name, data=result)
        seconds = 60
        if self.is_options:
            seconds = self.config_entry.options.get("probe_seconds", self.config_entry.data.get("probe_seconds",60))
        defaults = user_input or previous
        settings={**self.config_entry.data,**self.config_entry.options} if self.is_options else {}
        return self.async_show_form(step_id="manual", errors=errors, data_schema=vol.Schema({
            vol.Required("name", default=defaults.get("name", "MSpa")): str,
            vol.Required("model", default=defaults.get("model", "MSpa")): str,
            vol.Required("unicast_address_hex", default=defaults.get("unicast_address_hex", "0102")): str,
            vol.Optional("net_key", default=""): PASSWORD,
            vol.Optional('app_key',default=''):PASSWORD,
            vol.Required('controller_address_hex',default=(user_input or settings).get('controller_address_hex',CONTROLLER_ADDRESS)):str,
            vol.Required('poll_seconds',default=(user_input or settings).get('poll_seconds',POLL_SECONDS)):
                vol.All(vol.Coerce(int),vol.Range(min=30,max=600)),
            vol.Required("probe_seconds", default=defaults.get("probe_seconds",seconds)):
                vol.All(vol.Coerce(int), vol.Range(min=10,max=180)),
        }))


class MSpaLocalConfigFlow(SettingsSteps, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["login", "manual"])

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MSpaLocalOptionsFlow()


class MSpaLocalOptionsFlow(SettingsSteps, config_entries.OptionsFlow):
    is_options = True

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["manual", "login"])
