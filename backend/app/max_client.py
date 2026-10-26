from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import ssl
from typing import Any

import certifi
import httpx

from .config import get_settings

log = logging.getLogger("classgo.max")

DOWNLOAD_TIMEOUT = 30.0


class BlockedUrl(Exception):
    """Скачивание по ссылке из апдейта ушло бы не по https или внутрь сети сервера."""


async def public_https_only(request: httpx.Request) -> None:
    """Хук httpx на каждый запрос (и на каждый редирект): только https и адреса из интернета —
    не localhost, не локальная сеть, не служебные адреса облака (169.254.169.254)."""
    if request.url.scheme != "https":
        raise BlockedUrl(f"не https: {request.url.scheme}://{request.url.host}")
    host = request.url.host
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, request.url.port or 443,
                                                             type=socket.SOCK_STREAM)
    except OSError as err:
        raise BlockedUrl(f"адрес не найден: {host}") from err
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise BlockedUrl(f"внутренний адрес: {host} → {ip}")


class MaxClient:
    def __init__(self, token: str | None = None, base: str | None = None, timeout: float = 40.0) -> None:
        s = get_settings()
        self.token = token or s.MAX_BOT_TOKEN
        self.base = (base or s.MAX_API_BASE).rstrip("/")
        self.timeout = timeout
        if s.MAX_TLS_INSECURE:
            self.verify: bool | ssl.SSLContext = False
        elif s.MAX_CA_BUNDLE:
            # API MAX подписан «Russian Trusted Root CA», а сервер загрузки файлов (fu.oneme.ru) —
            # Let's Encrypt: доверяем обоим, а не только российскому корню.
            ctx = ssl.create_default_context(cafile=certifi.where())
            ctx.load_verify_locations(cafile=s.MAX_CA_BUNDLE)
            self.verify = ctx
        else:
            self.verify = True

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.token, "Content-Type": "application/json"}

    async def get_me(self) -> dict[str, Any] | None:
        return await self._request("GET", "/me")

    async def get_updates(self, marker: int | None = None, timeout: int = 30,
                          limit: int = 100, types: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return await self._request("GET", "/updates", params=params) or {"updates": [], "marker": marker}

    async def send_message(self, *, user_id: int | None = None, chat_id: int | None = None,
                           text: str = "", attachments: list[dict] | None = None,
                           fmt: str | None = None, notify: bool = True,
                           wait_attachments: bool = False) -> dict[str, Any] | None:
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id
        body: dict[str, Any] = {"text": text, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        if fmt:
            body["format"] = fmt
        return await self._request("POST", "/messages", params=params, json=body,
                                   retry_not_ready=5 if wait_attachments else 0)

    async def upload_file(self, content: bytes, filename: str, upload_type: str = "file") -> str | None:
        """Загружает файл в MAX и возвращает его attachment-token.

        Схема MAX (dev.max.ru): POST /uploads?type=... возвращает URL для загрузки,
        затем файл загружается на этот URL (multipart, поле ``data``), а в ответ
        приходит ``token``. Токен передаётся в POST /messages как вложение
        ``{"type": "file", "payload": {"token": ...}}``.
        Внешние ссылки в MAX запрещены — файл обязательно проходит через загрузку.
        """
        if not self.enabled:
            log.warning("MAX client disabled (нет токена): пропущена загрузка файла %s", filename)
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify) as client:
                init = await client.post(
                    f"{self.base}/uploads", params={"type": upload_type}, headers=self._headers()
                )
                if init.status_code >= 400:
                    log.error("MAX POST /uploads -> %s: %s", init.status_code, init.text[:300])
                    return None
                payload = init.json()
                upload_url = payload.get("url")
                if not upload_url:
                    log.error("MAX /uploads не вернул url: %s", payload)
                    return None
                # Загрузка идёт БЕЗ заголовка Content-Type: application/json —
                # иначе ломается multipart-boundary. Авторизация передаётся заголовком.
                resp = await client.post(
                    upload_url,
                    files={"data": (filename, content)},
                    headers={"Authorization": self.token},
                )
                if resp.status_code >= 400:
                    log.error("MAX upload %s -> %s: %s", upload_url, resp.status_code, resp.text[:300])
                    return None
                data = resp.json() if resp.content else {}
                return data.get("token")
        except Exception as exc:  # noqa: BLE001 — не роняем сервис из-за внешнего API
            log.error("MAX загрузка файла %s ошибка: %s", filename, exc)
            return None

    async def send_document(self, *, filename: str, token: str, caption: str = "",
                            chat_id: int | None = None, user_id: int | None = None) -> dict[str, Any] | None:
        """Отправляет ранее загруженный файл сообщением (вложение типа ``file``)."""
        attachment = {"type": "file", "payload": {"token": token, "filename": filename}}
        return await self.send_message(
            chat_id=chat_id, user_id=user_id, text=caption, attachments=[attachment], wait_attachments=True
        )

    async def download(self, url: str, limit: int = 12 * 1024 * 1024) -> bytes | None:
        """Вложение из сообщения (фото или файл) по ссылке, которую прислал MAX.

        Ссылка приходит в апдейте, поэтому на каждом шаге, включая редиректы, пускаем только https
        на публичные адреса (точного списка CDN MAX нет — белый список сломал бы приём билетов).
        Не больше трёх редиректов и 30 секунд на всё: медленная отдача не держит опрос бота.
        """
        if not self.enabled or not url.startswith("https://"):
            return None
        try:
            async with asyncio.timeout(DOWNLOAD_TIMEOUT):
                async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify, follow_redirects=True,
                                             max_redirects=3, event_hooks={"request": [public_https_only]}) as client:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code != 200:
                            log.warning("MAX download %s -> %s", url[:60], resp.status_code)
                            return None
                        chunks, size = [], 0
                        async for chunk in resp.aiter_bytes():
                            size += len(chunk)
                            if size > limit:
                                return None
                            chunks.append(chunk)
                        return b"".join(chunks)
        except (httpx.HTTPError, BlockedUrl, TimeoutError) as exc:
            log.warning("MAX download failed: %s", exc)
            return None

    async def set_commands(self, commands: list[dict[str, str]]) -> dict[str, Any] | None:
        return await self._request("PATCH", "/me/commands", json={"commands": commands})

    async def answer_callback(self, callback_id: str, *, text: str | None = None,
                              attachments: list[dict] | None = None,
                              notification: str | None = None) -> dict[str, Any] | None:
        body: dict[str, Any] = {}
        if text is not None or attachments is not None:
            message: dict[str, Any] = {}
            if text is not None:
                message["text"] = text
            if attachments is not None:
                message["attachments"] = attachments
            body["message"] = message
        if notification:
            body["notification"] = notification
        return await self._request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       json: dict | None = None, retry_not_ready: int = 0) -> dict[str, Any] | None:
        if not self.enabled:
            log.warning("MAX client disabled (нет токена): пропущен %s %s", method, path)
            return None
        url = f"{self.base}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify) as client:
                resp = await client.request(method, url, params=params, json=json, headers=self._headers())
                for attempt in range(retry_not_ready):
                    # Только что загруженный файл MAX ещё обрабатывает: просит повторить чуть позже.
                    if resp.status_code != 400 or "attachment.not.ready" not in resp.text:
                        break
                    await asyncio.sleep(1 + attempt)
                    resp = await client.request(method, url, params=params, json=json, headers=self._headers())
                if resp.status_code >= 400:
                    log.error("MAX %s %s -> %s: %s", method, path, resp.status_code, resp.text[:300])
                    return None
                if not resp.content:
                    return {}
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            log.error("MAX %s %s ошибка транспорта: %s", method, path, exc)
            return None


BOT_COMMANDS: list[dict[str, str]] = [
    {"name": "start", "description": "Начать работу с ClassGo"},
    {"name": "trips", "description": "Выезды моего ребёнка"},
    {"name": "mute", "description": "Выключить напоминания"},
    {"name": "unmute", "description": "Включить напоминания"},
    {"name": "help", "description": "Как это работает"},
]


def inline_keyboard(buttons: list[list[dict]]) -> dict:
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


def callback_button(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}


def link_button(text: str, url: str) -> dict:
    return {"type": "link", "text": text, "url": url}


def open_app_button(text: str, web_app: str, payload: str = "") -> dict:
    return {"type": "open_app", "text": text, "web_app": web_app, "payload": payload or None}
