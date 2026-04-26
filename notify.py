"""ClawBot 的通知平台（Notify）。

为每个配置条目创建一个通知实体，支持 Home Assistant 原生 notify.send_message 服务。
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hub import ClawBotHub

_LOGGER = logging.getLogger(__name__)


class ClawBotNotifyEntity(NotifyEntity):
    """ClawBot 通知实体，支持原生 notify.send_message 服务。"""

    _attr_has_entity_name = True
    _attr_name = "通知"
    _attr_icon = "mdi:message-text"

    def __init__(self, entry: ConfigEntry, hub: ClawBotHub) -> None:
        self._entry = entry
        self._hub = hub
        self._attr_unique_id = f"{entry.entry_id}_notify"
        self._last_from_user_id = ""
        self._last_context_token = ""
        self._unsub = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Weixin",
            model="ClawBot",
        )

    async def async_added_to_hass(self) -> None:
        """订阅接收消息事件以跟踪发送目标。"""
        self._unsub = self.hass.bus.async_listen(
            "ha_clawbot_message_received",
            self._handle_message_received,
        )

    async def async_will_remove_from_hass(self) -> None:
        """从 Home Assistant 移除时取消订阅。"""
        if self._unsub:
            self._unsub()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "entry_id": self._entry.entry_id,
            "target_user_id": self._last_from_user_id,
            "context_token": self._last_context_token,
        }

    @callback
    def _handle_message_received(self, event) -> None:
        """更新最近的发件人和 context_token 以用于回复。"""
        data = event.data or {}
        if data.get("entry_id") != self._entry.entry_id:
            return

        self._last_from_user_id = data.get("from_user_id", "")
        self._last_context_token = data.get("context_token", "")
        self.async_write_ha_state()

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """发送通知消息，与 ClawBotSendMessage 相同的发送逻辑。"""
        text = f"{title}\n\n{message}" if title else message

        target_user_id = self._last_from_user_id
        context_token = self._last_context_token

        if not target_user_id:
            target_user_id = ""
            context_token = ""

        if not target_user_id:
            _LOGGER.error("ClawBot 通知：未配置接收者")
            return

        _LOGGER.debug("ClawBot 通知发送到 %s，context_token=%s", target_user_id, context_token)
        try:
            await self._hub.async_send_message(
                target_user_id,
                text,
                context_token,
            )
        except Exception:
            _LOGGER.exception("ClawBot 通知发送失败")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """从配置条目设置 ClawBot 通知实体。"""
    hub_entry = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not hub_entry:
        return

    hub = hub_entry.get("hub")
    if not hub:
        return

    async_add_entities([ClawBotNotifyEntity(entry, hub)])
