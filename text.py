"""ClawBot 的文本平台（Text）。

创建两个文本实体：
1. 接收消息实体：显示最新接收到的消息（只读）
2. 发送消息实体：用于输入和发送消息
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_ILINK_USER_ID

_LOGGER = logging.getLogger(__name__)


class ClawBotReceivedMessage(TextEntity):
    """表示接收到的消息的文本实体（只读）。"""

    _attr_has_entity_name = True
    _attr_name = "接收消息"
    _attr_icon = "mdi:email-arrow-right"
    _attr_editable = False

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_received_message"
        self._attr_native_value = ""
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "entry_id": self._entry.entry_id,
            "from_user_id": self._last_from_user_id,
            "context_token": self._last_context_token,
        }

    async def async_added_to_hass(self) -> None:
        """添加到 Home Assistant 时订阅接收消息事件。"""
        self._unsub = self.hass.bus.async_listen(
            "ha_clawbot_message_received",
            self._handle_message_received,
        )

    async def async_will_remove_from_hass(self) -> None:
        """从 Home Assistant 移除时取消订阅。"""
        if self._unsub:
            self._unsub()

    @callback
    def _handle_message_received(self, event) -> None:
        """处理接收到的消息事件并更新状态。"""
        data = event.data or {}
        if data.get("entry_id") != self._entry.entry_id:
            return

        self._last_from_user_id = data.get("from_user_id", "")
        self._last_context_token = data.get("context_token", "")
        self._attr_native_value = data.get("text", "")
        self.async_write_ha_state()


class ClawBotSendMessage(TextEntity):
    """表示用于发送消息的文本实体。"""

    _attr_has_entity_name = True
    _attr_name = "发送消息"
    _attr_icon = "mdi:email-arrow-left"
    _attr_editable = True

    def __init__(self, entry: ConfigEntry, hub: Any):
        self._entry = entry
        self._hub = hub
        self._attr_unique_id = f"{entry.entry_id}_send_message"
        self._attr_native_value = ""
        self._last_from_user_id = entry.data.get(CONF_ILINK_USER_ID, "")
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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "entry_id": self._entry.entry_id,
            "target_user_id": self._last_from_user_id,
            "context_token": self._last_context_token,
        }

    async def async_added_to_hass(self) -> None:
        """添加到 Home Assistant 时订阅接收消息事件以跟踪发送目标。"""
        self._unsub = self.hass.bus.async_listen(
            "ha_clawbot_message_received",
            self._handle_message_received,
        )

    async def async_will_remove_from_hass(self) -> None:
        """从 Home Assistant 移除时取消订阅。"""
        if self._unsub:
            self._unsub()

    @callback
    def _handle_message_received(self, event) -> None:
        """更新最近的发件人和 context_token 以用于回复。"""
        data = event.data or {}
        if data.get("entry_id") != self._entry.entry_id:
            return

        self._last_from_user_id = data.get("from_user_id", "")
        self._last_context_token = data.get("context_token", "")
        self.async_write_ha_state()

    async def async_set_value(self, value: str) -> None:
        """设置文本值以通过 ClawBot 发送消息。"""
        if not value:
            return

        target_user_id = self._last_from_user_id
        context_token = self._last_context_token
        
        if not target_user_id:
            target_user_id = self._entry.data.get(CONF_ILINK_USER_ID, "")
            context_token = ""

        if not target_user_id:
            _LOGGER.error("未配置接收者")
            self._attr_native_value = "错误：未配置接收者"
            self.async_write_ha_state()
            return

        _LOGGER.debug("发送消息到 %s，context_token=%s", target_user_id, context_token)
        try:
            result = await self._hub.async_send_message(
                target_user_id,
                value,
                context_token,
            )
            _LOGGER.debug("发送结果：%s", result)
            self._attr_native_value = f"✓ 已发送到 {target_user_id.split('@')[0]}"
        except Exception as e:
            _LOGGER.exception("发送消息失败")
            self._attr_native_value = f"✗ 错误：{str(e)}"

        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """从配置条目设置 ClawBot 文本实体。"""
    hub_entry = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not hub_entry:
        return

    hub = hub_entry.get("hub")
    if not hub:
        return

    async_add_entities([
        ClawBotReceivedMessage(entry),
        ClawBotSendMessage(entry, hub),
    ])
