# SPDX-License-Identifier: Apache-2.0
"""Shared entity metadata, separate IDs from the cloud integration."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


class MSpaEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name, *, diagnostic=False):
        super().__init__(coordinator)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.profile.unique_id}_{key}"
        if diagnostic:self._attr_entity_category=EntityCategory.DIAGNOSTIC
        wifi=coordinator.profile.wifi_version
        mcu=coordinator.profile.mcu_version.removeprefix('mcu-')
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.profile.unique_id)},
            name=coordinator.profile.name, manufacturer="MSpa",
            model=coordinator.profile.model, sw_version='-'.join(x for x in (wifi,mcu) if x) or None,
        )

    @property
    def available(self):
        return super().available and bool(self.coordinator.data)
