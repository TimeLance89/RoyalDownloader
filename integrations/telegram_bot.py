"""Kleiner Telegram-Bot-API-Client mit Long Polling, ohne Zusatzpakete."""

import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional


class TelegramBot:
    def __init__(
        self,
        config_cb: Callable[[], dict],
        message_cb: Callable[[str, str, str], None],
        log_cb: Optional[Callable[[str, str], None]] = None,
        callback_cb: Optional[Callable[[str, str, str, str], None]] = None,
    ):
        self.config_cb = config_cb
        self.message_cb = message_cb
        self.log_cb = log_cb or (lambda _msg, _level="": None)
        self.callback_cb = callback_cb
        self._offset: Optional[int] = None
        self._active_token = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_error = ""

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="telegram-bot")
        self._thread.start()

    def stop(self):
        self._running = False

    @staticmethod
    def _parse_response(resp, method: str) -> dict:
        result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(result.get("description") or f"Telegram {method} fehlgeschlagen")
        return result

    @classmethod
    def _request(cls, token: str, method: str, payload: dict, timeout: int = 15) -> dict:
        url = f"https://api.telegram.org/bot{token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return cls._parse_response(resp, method)

    @classmethod
    def _multipart_request(
        cls,
        token: str,
        method: str,
        fields: dict,
        file_field: str,
        content: bytes,
        filename: str,
        content_type: str,
        timeout: int = 30,
    ) -> dict:
        boundary = f"----RoyalDownloader{secrets.token_hex(12)}"
        body = bytearray()
        for name, value in fields.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii")
            )
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n'.encode("ascii")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("ascii"))
        body.extend(content)
        body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=bytes(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return cls._parse_response(resp, method)

    @staticmethod
    def _message_id(result: dict) -> Optional[int]:
        value = (result.get("result") or {}).get("message_id")
        return value if isinstance(value, int) else None

    def send_message(
        self, chat_id: str, text: str, reply_markup: Optional[dict] = None,
    ) -> Optional[int]:
        cfg = self.config_cb()
        token = str(cfg.get("bot_token", "")).strip()
        if not token or not chat_id:
            return None
        payload = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            return self._message_id(self._request(token, "sendMessage", payload))
        except Exception as exc:
            self.log_cb(f"Telegram-Antwort fehlgeschlagen: {exc}", "warn")
            return None

    def send(self, chat_id: str, text: str) -> bool:
        return self.send_message(chat_id, text) is not None

    def send_photo(
        self,
        chat_id: str,
        photo: str | bytes,
        caption: str,
        reply_markup: Optional[dict] = None,
        content_type: str = "image/jpeg",
    ) -> Optional[int]:
        cfg = self.config_cb()
        token = str(cfg.get("bot_token", "")).strip()
        if not token or not chat_id or not photo:
            return None
        fields = {"chat_id": chat_id, "caption": caption[:1024]}
        if reply_markup:
            fields["reply_markup"] = reply_markup
        try:
            if isinstance(photo, bytes):
                extension = {
                    "image/png": "png",
                    "image/webp": "webp",
                }.get(content_type, "jpg")
                result = self._multipart_request(
                    token,
                    "sendPhoto",
                    fields,
                    "photo",
                    photo,
                    f"cover.{extension}",
                    content_type,
                )
            else:
                result = self._request(token, "sendPhoto", {**fields, "photo": photo})
            return self._message_id(result)
        except Exception as exc:
            self.log_cb(f"Telegram-Bild fehlgeschlagen: {exc}", "warn")
            return None

    def answer_callback(self, callback_query_id: str, text: str = "") -> bool:
        cfg = self.config_cb()
        token = str(cfg.get("bot_token", "")).strip()
        if not token or not callback_query_id:
            return False
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        try:
            self._request(token, "answerCallbackQuery", payload)
            return True
        except Exception as exc:
            self.log_cb(f"Telegram-Callback-Antwort fehlgeschlagen: {exc}", "warn")
            return False

    def clear_inline_keyboard(self, chat_id: str, message_id: int) -> bool:
        cfg = self.config_cb()
        token = str(cfg.get("bot_token", "")).strip()
        if not token or not chat_id or not message_id:
            return False
        try:
            self._request(token, "editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            })
            return True
        except Exception as exc:
            self.log_cb(f"Telegram-Auswahlbutton konnte nicht entfernt werden: {exc}", "warn")
            return False

    def _log_error_once(self, message: str):
        if message != self._last_error:
            self._last_error = message
            self.log_cb(message, "warn")

    def _dispatch_update(self, update: dict) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            self._offset = max(self._offset or 0, update_id + 1)

        callback = update.get("callback_query") or {}
        if callback and self.callback_cb:
            message = callback.get("message") or {}
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id") or "")
            callback_id = str(callback.get("id") or "")
            data = str(callback.get("data") or "")
            sender = callback.get("from") or {}
            sender_name = str(sender.get("username") or sender.get("first_name") or "")
            if chat_id and callback_id and data:
                threading.Thread(
                    target=self.callback_cb,
                    args=(chat_id, callback_id, data, sender_name),
                    daemon=True,
                ).start()
            return

        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        sender = message.get("from") or {}
        sender_name = str(sender.get("username") or sender.get("first_name") or "")
        if not text or not chat_id:
            return
        threading.Thread(
            target=self.message_cb,
            args=(chat_id, text, sender_name),
            daemon=True,
        ).start()

    def _loop(self):
        while self._running:
            cfg = self.config_cb()
            enabled = bool(cfg.get("enabled"))
            token = str(cfg.get("bot_token", "")).strip()
            if not enabled or not token:
                self._active_token = ""
                self._offset = None
                time.sleep(2)
                continue

            if token != self._active_token:
                self._active_token = token
                self._offset = None
                self._last_error = ""
                self.log_cb("Telegram-Bot aktiviert.")

            payload = {"timeout": 25, "allowed_updates": ["message", "callback_query"]}
            if self._offset is not None:
                payload["offset"] = self._offset
            try:
                data = self._request(token, "getUpdates", payload, timeout=35)
                self._last_error = ""
                for update in data.get("result", []):
                    self._dispatch_update(update)
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = str(exc)
                self._log_error_once(f"Telegram-Polling fehlgeschlagen ({exc.code}): {detail[:180]}")
                time.sleep(5)
            except Exception as exc:
                self._log_error_once(f"Telegram-Polling fehlgeschlagen: {exc}")
                time.sleep(5)
