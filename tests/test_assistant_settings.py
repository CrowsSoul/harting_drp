# -*- coding: utf-8 -*-
"""DeepSeek 设置：本机加密保存、掩码展示、清除与客户端回退。"""

import sys
import tempfile
import unittest
from pathlib import Path

from nxdrp.assistant.client import DeepSeekClient
from nxdrp.assistant.settings import AssistantSettings, SettingsError


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="assistant-settings-")
        self.path = Path(self.tmp.name) / "assistant" / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_is_encrypted_and_masked(self):
        settings = AssistantSettings(self.path)
        public = settings.save(
            api_key="sk-test-1234567890", model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        self.assertTrue(public["configured"])
        self.assertTrue(public["masked"].endswith("7890"))
        self.assertNotIn("sk-test-1234567890", str(public))
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("sk-test-1234567890", raw, "密钥不能明文落盘")
        if sys.platform == "win32":
            self.assertIn("dpapi", raw)
            self.assertTrue(public["secure"])
        # 新实例（模拟重启）仍能解出密钥
        reloaded = AssistantSettings(self.path)
        self.assertEqual(reloaded.api_key(), "sk-test-1234567890")
        self.assertEqual(reloaded.model(), "deepseek-chat")

    def test_clear_key(self):
        settings = AssistantSettings(self.path)
        settings.save(api_key="sk-test-1234567890")
        public = settings.save(clear_key=True)
        self.assertFalse(public["configured"])
        self.assertEqual(settings.api_key(), "")
        self.assertNotIn("sk-test", self.path.read_text(encoding="utf-8"))

    def test_rejects_invalid_key_and_url(self):
        settings = AssistantSettings(self.path)
        with self.assertRaises(SettingsError):
            settings.save(api_key="bad key with spaces")
        with self.assertRaises(SettingsError):
            settings.save(base_url="not-a-url")

    def test_client_falls_back_to_saved_secret(self):
        settings = AssistantSettings(self.path)
        settings.save(api_key="sk-test-1234567890")
        client = DeepSeekClient(api_key="", secret_provider=settings.api_key)
        self.assertTrue(client.enabled())
        self.assertEqual(client.describe()["source"], "saved")
        empty = DeepSeekClient(api_key="", secret_provider=lambda: "")
        self.assertFalse(empty.enabled())


if __name__ == "__main__":
    unittest.main()
