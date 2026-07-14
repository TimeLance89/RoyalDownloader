import json
import unittest
from unittest.mock import patch

from telegram_bot import TelegramBot


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ImmediateThread:
    def __init__(self, target, args=(), **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.callbacks = []
        self.bot = TelegramBot(
            lambda: {"bot_token": "token", "enabled": True},
            lambda *args: self.messages.append(args),
            callback_cb=lambda *args: self.callbacks.append(args),
        )

    @patch("urllib.request.urlopen")
    def test_send_photo_url_includes_inline_keyboard(self, urlopen):
        urlopen.return_value = FakeResponse({"ok": True, "result": {"message_id": 17}})
        markup = {"inline_keyboard": [[{
            "text": "Diese Serie auswählen", "callback_data": "sr:abcdefgh:0",
        }]]}

        message_id = self.bot.send_photo(
            "123", "https://example.test/cover.jpg", "Treffer", markup,
        )

        self.assertEqual(message_id, 17)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["photo"], "https://example.test/cover.jpg")
        self.assertEqual(payload["reply_markup"], markup)
        self.assertTrue(request.full_url.endswith("/sendPhoto"))

    @patch("urllib.request.urlopen")
    def test_send_photo_bytes_uses_multipart_upload(self, urlopen):
        urlopen.return_value = FakeResponse({"ok": True, "result": {"message_id": 18}})
        markup = {"inline_keyboard": [[{
            "text": "Auswählen", "callback_data": "sr:abcdefgh:0",
        }]]}

        message_id = self.bot.send_photo(
            "123", b"image-bytes", "Poster", markup, content_type="image/png",
        )

        self.assertEqual(message_id, 18)
        request = urlopen.call_args.args[0]
        self.assertIn("multipart/form-data", request.get_header("Content-type"))
        self.assertIn(b'filename="cover.png"', request.data)
        self.assertIn(b"image-bytes", request.data)
        self.assertIn(b'sr:abcdefgh:0', request.data)

    @patch("urllib.request.urlopen")
    def test_photo_caption_is_limited_to_telegram_maximum(self, urlopen):
        urlopen.return_value = FakeResponse({"ok": True, "result": {"message_id": 19}})

        self.bot.send_photo("123", "https://example.test/cover.jpg", "x" * 2000)

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(len(payload["caption"]), 1024)

    @patch("telegram_bot.threading.Thread", ImmediateThread)
    def test_callback_query_is_dispatched_with_chat_and_sender(self):
        self.bot._dispatch_update({
            "update_id": 41,
            "callback_query": {
                "id": "callback-1",
                "data": "sr:abcdefgh:1",
                "message": {"chat": {"id": 123}},
                "from": {"username": "tester"},
            },
        })

        self.assertEqual(
            self.callbacks,
            [("123", "callback-1", "sr:abcdefgh:1", "tester")],
        )
        self.assertEqual(self.bot._offset, 42)
        self.assertEqual(self.messages, [])


if __name__ == "__main__":
    unittest.main()
