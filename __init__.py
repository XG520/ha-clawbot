"""Weixin ClawBot 集成的 Home Assistant 组件。"""

import logging

from .const import CONF_BOT_TOKEN, CONF_BASE_URL, DOMAIN
from .hub import ClawBotHub

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    """设置集成。"""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass, entry):
    """从配置条目设置集成。"""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_BOT_TOKEN: entry.data[CONF_BOT_TOKEN],
        CONF_BASE_URL: entry.data[CONF_BASE_URL],
    }

    hub = ClawBotHub(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["hub"] = hub
    await hub.async_start()

    await hass.config_entries.async_forward_entry_setups(entry, ["text", "notify"])

    _LOGGER.debug("ClawBot 条目已加载：%s，base_url=%s", entry.title, entry.data[CONF_BASE_URL])

    return True


async def async_unload_entry(hass, entry):
    """卸载配置条目。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["text", "notify"])

    if unload_ok:
        entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if entry_data is not None:
            hub = entry_data.get("hub")
            if hub is not None:
                await hub.async_stop()

        _LOGGER.debug("ClawBot 条目已卸载：%s", entry.title)

    return unload_ok
