"""轻量级 ClawBot hub，用于保存 token 与 base URL。

提供长轮询（`getupdates`）和发送消息（`sendmessage`）的辅助方法，
并为接收的消息提供调试日志与事件分发。
"""

import asyncio
import base64
import json
import logging
import random
import re
import uuid
from typing import Any

import aiohttp
from aiohttp import client_exceptions

from .const import CONF_BOT_TOKEN, CONF_BASE_URL, DEFAULT_BASE_URL

_LOGGER = logging.getLogger(__name__)

CHANNEL_VERSION = "1.0.0"


def _build_client_version(version: str) -> int:
    """构建客户端版本号：0x00MMNNPP 格式。"""
    parts = version.split(".")
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


ILINK_APP_CLIENT_VERSION = _build_client_version(CHANNEL_VERSION)


class ClawBotHub:
    """表示已配置的 ClawBot 实例的 Hub 对象。

    方法说明：
    - `async_start()`：启动后台长轮询任务。
    - `async_stop()`：停止并取消后台任务。
    - `async_send_message(...)`：通过 iLink 的 `sendmessage` 发送文本消息。
    """

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.bot_token = entry.data[CONF_BOT_TOKEN]
        # 清理 base_url 的多余字符
        raw_url = entry.data[CONF_BASE_URL]
        url_match = re.search(r'https?://[^\s`"\']+', raw_url)
        self.base_url = url_match.group(0) if url_match else DEFAULT_BASE_URL

        self._task: asyncio.Task | None = None
        self._session = None
        self._get_updates_buf = ""

        _LOGGER.debug(
            "初始化 ClawBotHub，条目=%s，base_url=%s",
            entry.title,
            self.base_url,
        )

    def _generate_x_wechat_uin(self) -> str:
        """生成 X-WECHAT-UIN：随机 uint32 的 base64 编码。"""
        random_u32 = random.randint(0, 0xFFFFFFFF)
        uin_str = str(random_u32)
        return base64.b64encode(uin_str.encode()).decode()

    @property
    def headers(self) -> dict[str, str]:
        """返回 ClawBot 请求所需的标准请求头。"""
        return {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": self._generate_x_wechat_uin(),
            "iLink-App-Id": "",
            "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
            "Authorization": f"Bearer {self.bot_token}",
        }

    async def async_start(self) -> None:
        """启动后台长轮询监听任务。"""
        if self._task is not None and not self._task.done():
            return
        connector = aiohttp.TCPConnector(ssl=False)
        self._session = aiohttp.ClientSession(connector=connector)
        self._task = self.hass.loop.create_task(self._listen_loop())
        _LOGGER.debug("ClawBotHub 监听任务已启动")

    async def async_stop(self) -> None:
        """停止后台任务并关闭会话。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None
        _LOGGER.debug("ClawBotHub 已停止")

    def _url(self, path: str) -> str:
        """构建完整 URL，确保 base_url 有尾部斜杠。"""
        base = self.base_url if self.base_url.endswith("/") else f"{self.base_url}/"
        return f"{base}{path.lstrip('/')}"

    async def _post_json(self, path: str, payload: Any) -> Any:
        """向 iLink API 发送 JSON POST 请求并返回解析后的 JSON。"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)

        url = self._url(path)
        headers_to_log = dict(self.headers)
        if "Authorization" in headers_to_log:
            headers_to_log["Authorization"] = "Bearer ***"
        _LOGGER.debug("POST %s 请求头=%s 载荷=%s", url, headers_to_log, payload)
        
        async with self._session.post(url, json=payload, headers=self.headers) as resp:
            _LOGGER.debug("响应状态=%d 响应头=%s", resp.status, dict(resp.headers))
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            _LOGGER.debug("响应体=%s", data)
            return data

    async def async_send_message(self, to_user_id: str, text: str, context_token: str = "") -> Any:
        """通过 iLink 的 `sendmessage` API 发送文本消息。

        返回 API 的响应 JSON。
        """
        msg = {
            "from_user_id": "",  # 服务端自动填充
            "to_user_id": to_user_id,
            "client_id": str(uuid.uuid4()),  # 防止重复消息
            "message_type": 2,  # 2 = BOT
            "message_state": 2,  # 2 = FINISH
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }
        if context_token:
            msg["context_token"] = context_token
        
        payload = {
            "msg": msg,
            "base_info": {"channel_version": CHANNEL_VERSION},
        }
        _LOGGER.debug("发送消息到 %s：%s", to_user_id, text)
        try:
            resp = await self._post_json("/ilink/bot/sendmessage", payload)
            _LOGGER.debug("sendmessage 响应：%s", json.dumps(resp, ensure_ascii=False))
            
            if isinstance(resp, dict) and "ret" in resp and resp.get("ret") != 0:
                ret_code = resp.get("ret")
                if ret_code == -2:
                    error_msg = "会话未建立，请先让用户发送一条消息"
                else:
                    error_msg = f"API 错误：{resp}"
                _LOGGER.error("API 返回错误：%s", resp)
                raise Exception(error_msg)
                
            return resp
        except Exception as e:
            _LOGGER.exception("发送消息到 %s 失败", to_user_id)
            raise

    async def _listen_loop(self) -> None:
        """执行长轮询 `getupdates` 的循环并记录接收到的消息。"""
        _LOGGER.debug("进入 ClawBotHub 长轮询循环")

        while True:
            try:
                if self._session is None or self._session.closed:
                    connector = aiohttp.TCPConnector(ssl=False)
                    self._session = aiohttp.ClientSession(connector=connector)
                
                payload = {"get_updates_buf": self._get_updates_buf, "base_info": {"channel_version": "1.0.0"}}
                url = self._url("/ilink/bot/getupdates")
                _LOGGER.debug("长轮询 %s 缓冲区=%s", url, self._get_updates_buf)
                async with self._session.post(url, json=payload, headers=self.headers, timeout=40) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)

                _LOGGER.debug("getupdates 响应：%s", data)

                self._get_updates_buf = data.get("get_updates_buf", self._get_updates_buf)

                for msg in data.get("msgs", []) or []:
                    try:
                        from_id = msg.get("from_user_id")
                        items = msg.get("item_list", [])
                        text = None
                        if items:
                            first = items[0]
                            if first.get("type") == 1:
                                text = first.get("text_item", {}).get("text")

                        _LOGGER.debug("收到来自 %s 的消息：%s", from_id, text)
                        
                        context_token = msg.get("context_token")
                        try:
                            hass_map = self.hass.data.setdefault("ha-clawbot", {})
                            entry_map = hass_map.setdefault(getattr(self.entry, "entry_id", ""), {})
                            last_context = entry_map.setdefault("last_context", {})
                            if context_token:
                                last_context[from_id] = context_token
                        except Exception:
                            _LOGGER.debug("无法持久化 %s 的 context_token", from_id)

                        try:
                            self.hass.bus.async_fire(
                                "ha_clawbot_message_received",
                                {
                                    "entry_id": getattr(self.entry, "entry_id", None),
                                    "from_user_id": from_id,
                                    "text": text,
                                    "context_token": context_token,
                                    "raw": msg,
                                },
                            )
                        except Exception:
                            _LOGGER.exception("无法为 %s 触发消息接收事件", from_id)
                    except Exception:
                        _LOGGER.exception("处理 incoming 消息失败：%s", msg)

            except asyncio.CancelledError:
                _LOGGER.debug("ClawBotHub 监听循环已取消")
                break
            except (client_exceptions.ServerDisconnectedError, aiohttp.ClientConnectionError) as err:
                _LOGGER.warning("ClawBotHub 监听循环连接错误：%s。5秒后重试", err)
                await asyncio.sleep(5)
            except Exception:
                _LOGGER.exception("ClawBotHub 监听循环发生意外错误，5秒后重试")
                await asyncio.sleep(5)
