"""Weixin ClawBot 集成的配置流程（Config Flow）。"""

from __future__ import annotations

import base64
import io
import logging
import re
from urllib.parse import urlencode, quote_plus
import segno

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    CONF_BASE_URL,
    CONF_BOT_TOKEN,
    CONF_ILINK_USER_ID,
    DEFAULT_BASE_URL,
    DOMAIN,
    ENDPOINT_GET_QR,
    ENDPOINT_GET_QR_STATUS,
)

_LOGGER = logging.getLogger(__name__)


class ClawBotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """处理 Weixin ClawBot 的配置流程。"""

    VERSION = 1

    def __init__(self):
        self._bot_data: dict[str, str] = {}
        self._username: str | None = None

    async def async_step_user(self, user_input=None):
        """处理配置流程的初始步骤（用户名输入）。"""
        if user_input is not None:
            self._username = user_input[CONF_NAME]
            _LOGGER.debug("收到用户名 %s，进入二维码步骤", self._username)
            return await self.async_step_qr()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NAME): str}),
        )

    async def async_step_qr(self, user_input=None):
        """显示二维码并等待用户确认扫码。"""
        if self._username is None:
            _LOGGER.debug("用户名缺失，返回用户步骤")
            return await self.async_step_user()

        if user_input is not None:
            _LOGGER.debug("用户提交二维码确认步骤，用户名=%s", self._username)
            status = await self._async_check_qrcode_status()
            if status is None:
                _LOGGER.debug("二维码尚未确认，提示用户重试")
                return self._show_qr_form(errors={"base": "scan_pending"})

            if status.get("status") != "confirmed":
                _LOGGER.debug("二维码状态异常：%s", status.get("status"))
                return self._show_qr_form(errors={"base": "scan_pending"})

            _LOGGER.debug("二维码已确认，创建配置条目，用户名=%s", self._username)
            baseurl = status.get("baseurl", DEFAULT_BASE_URL)
            if baseurl:
                url_match = re.search(r'https?://[^\s`"\']+', baseurl)
                if url_match:
                    baseurl = url_match.group(0)
                else:
                    baseurl = DEFAULT_BASE_URL
                _LOGGER.debug("清理后的 baseurl：%s", baseurl)
            else:
                baseurl = DEFAULT_BASE_URL
            
            return self.async_create_entry(
                title=f"Weixin ClawBot ({self._username})",
                data={
                    CONF_BOT_TOKEN: status["bot_token"],
                    CONF_BASE_URL: baseurl,
                    CONF_ILINK_USER_ID: status.get("ilink_user_id"),
                },
            )

        _LOGGER.debug("获取 ClawBot 登录二维码")
        try:
            qr_code_data = await self._async_get_qr_code()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("获取 ClawBot 登录二维码失败")
            return self.async_show_form(
                step_id="qr",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
                description_placeholders={
                    "qrcode_image": "",
                    "qrcode": "",
                    "qrcode_page": "",
                },
            )

        self._bot_data = qr_code_data
        _LOGGER.debug(
            "获取到二维码数据：qrcode=%s，content=%s",
            qr_code_data.get("qrcode"),
            qr_code_data.get("qrcode_img_content"),
        )
        return self._show_qr_form()

    def _show_qr_form(self, errors: dict[str, str] | None = None):
        """向用户显示扫码表单（含二维码或扫码链接）。"""
        qr_content = self._bot_data.get("qrcode_img_content", "")
        if qr_content.startswith("http"):
            _LOGGER.debug("显示远程二维码链接")
            data_schema = vol.Schema({vol.Optional("scan_url", default=qr_content): str})
            try:
                qrcode_image = self._generate_external_qr_image(qr_content)
            except Exception:  # fallback to empty if generation fails
                _LOGGER.exception("生成外部二维码图片失败")
                qrcode_image = ""
        elif qr_content.startswith("data:image"):
            _LOGGER.debug("显示内联二维码（data URI）")
            data_schema = vol.Schema({})
            qrcode_image = qr_content
        else:
            _LOGGER.debug("显示内联二维码（Base64）")
            data_schema = vol.Schema({})
            qrcode_image = f"data:image/png;base64,{qr_content}"

        return self.async_show_form(
            step_id="qr",
            data_schema=data_schema,
            description_placeholders={
                "qrcode_image": qrcode_image,
                "qrcode": qr_content,
                "qrcode_page": qr_content,
            },
            errors=errors or {},
        )

    def _generate_external_qr_image(self, qr_data: str) -> str:
        """使用外部服务生成远程二维码图片 URL。"""
        encoded = quote_plus(qr_data)
        return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"

    def _encode_qr_image(self, qr_data: str) -> str:
        """从 URL 或文本生成 base64 编码的二维码图片。"""
        buffer = io.BytesIO()
        qr = segno.make(qr_data)
        qr.save(buffer, kind="png", scale=4, dark="#000000", light="#ffffff")
        buffer.seek(0)
        encoded = base64.b64encode(buffer.read()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    async def _async_get_qr_code(self) -> dict[str, str]:
        """从 iLink API 获取二维码载荷。"""
        session = async_create_clientsession(self.hass)
        url = f"{DEFAULT_BASE_URL}{ENDPOINT_GET_QR}?bot_type=3"
        _LOGGER.debug("请求二维码：%s", url)
        response = await session.get(url)
        response.raise_for_status()

        try:
            data = await response.json(content_type=None)
        except Exception as err:  # noqa: BLE001
            text = await response.text()
            _LOGGER.error(
                "解析二维码响应失败：%s，响应头=%s，响应体=%s",
                err,
                dict(response.headers),
                text,
            )
            raise

        _LOGGER.debug("二维码响应：%s", data)
        return data

    async def _async_check_qrcode_status(self) -> dict[str, str] | None:
        """查询 iLink API，判断二维码是否已被扫码确认。"""
        if not self._bot_data.get("qrcode"):
            _LOGGER.debug("缺少二维码数据，无法检查状态")
            return None

        session = async_create_clientsession(self.hass)
        params = {"qrcode": self._bot_data["qrcode"]}
        url = f"{DEFAULT_BASE_URL}{ENDPOINT_GET_QR_STATUS}?{urlencode(params)}"
        _LOGGER.debug("检查二维码状态：%s", url)
        response = await session.get(url)
        response.raise_for_status()

        try:
            data = await response.json(content_type=None)
        except Exception as err:  # noqa: BLE001
            text = await response.text()
            _LOGGER.error(
                "解析二维码状态响应失败：%s，响应头=%s，响应体=%s",
                err,
                dict(response.headers),
                text,
            )
            raise

        _LOGGER.debug("二维码状态响应：%s", data)
        return data
