# -*- coding: utf-8 -*-
"""DeepSeek 客户端与解析编排：工具调用、修复轮、降级、重试、密钥脱敏。

全部用假传输，不联网。真实连通性用 ``python -m nxdrp.assistant doctor`` 验证。
"""

import json
import os
import unittest
from unittest.mock import patch

from nxdrp.assistant import context, planner
from nxdrp.assistant.client import DeepSeekClient, DeepSeekError


def tool_reply(spec: dict, call_id: str = "call-1") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "emit_task_spec",
                                "arguments": json.dumps(spec, ensure_ascii=False),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"total_tokens": 42},
    }


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "json": json.loads(body)})
        status, payload = self.responses.pop(0)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        return status, raw


def client_with(responses, **kwargs):
    fake = FakeTransport(responses)
    return DeepSeekClient(api_key="sk-test-key", transport=fake, sleep=lambda _: None, **kwargs), fake


VALID = {
    "spec_version": "1.0",
    "intent": "check",
    "instruction": "board_a 跑 DFM-31",
    "model": {"ref": "board_a", "kind": "sample"},
    "checks": {"only": ["DFM-31"]},
}


class ClientTests(unittest.TestCase):
    def test_call_uses_tools_and_auth(self):
        client, fake = client_with([(200, tool_reply(VALID))])
        result = client.chat([{"role": "user", "content": "x"}], tools=[{"type": "function"}],
                             tool_choice={"type": "function", "function": {"name": "emit_task_spec"}})
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "emit_task_spec")
        call = fake.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test-key")
        self.assertEqual(call["json"]["model"], client.model)
        self.assertFalse(call["json"]["stream"])

    def test_retry_on_429_then_success(self):
        client, fake = client_with([(429, {"error": {"message": "rate limited"}}),
                                    (200, tool_reply(VALID))])
        client.chat([{"role": "user", "content": "x"}])
        self.assertEqual(client.last_attempts, 2)
        self.assertEqual(len(fake.calls), 2)

    def test_auth_error_is_not_retried_and_key_redacted(self):
        client, fake = client_with(
            [(401, {"error": {"message": "invalid key sk-test-key"}})]
        )
        with self.assertRaises(DeepSeekError) as caught:
            client.chat([{"role": "user", "content": "x"}])
        message = str(caught.exception)
        self.assertNotIn("sk-test-key", message)
        self.assertIn("***", message)
        self.assertEqual(len(fake.calls), 1)

    def test_disabled_without_key(self):
        client = DeepSeekClient(api_key="")
        self.assertFalse(client.enabled())
        with self.assertRaises(DeepSeekError):
            client.chat([{"role": "user", "content": "x"}])

    def test_offline_switch_overrides_key(self):
        with patch.dict(os.environ, {"NXDRP_ASSISTANT_OFFLINE": "1"}):
            client = DeepSeekClient(api_key="sk-test-key")
            self.assertFalse(client.enabled())


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.models = context.available_models()
        self.checks = context.check_catalog()

    def test_llm_tool_call_becomes_validated_spec(self):
        client, fake = client_with([(200, tool_reply(VALID))])
        result = planner.plan("board_a 跑 DFM-31", models=self.models, checks=self.checks, client=client)
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.spec.model.ref, "board_a")
        self.assertEqual(result.missing, [])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["json"]["tool_choice"]["function"]["name"], "emit_task_spec")

    def test_invalid_tool_call_repaired_once(self):
        broken = dict(VALID, checks={"only": ["DFM-99"]})
        client, fake = client_with([(200, tool_reply(broken)), (200, tool_reply(VALID, "call-2"))])
        result = planner.plan("board_a 跑 DFM-99", models=self.models, checks=self.checks, client=client)
        self.assertEqual(result.source, "llm")
        self.assertEqual(len(fake.calls), 2)

    def test_http_failure_falls_back_to_offline_rules(self):
        client, _ = client_with([(401, {"error": {"message": "bad key"}})])
        result = planner.plan("board_a 跑 DFM-31", models=self.models, checks=self.checks, client=client)
        self.assertEqual(result.source, "fallback")
        self.assertEqual(result.spec.model.ref, "board_a")
        self.assertTrue(any("DeepSeek" in w for w in result.warnings))

    def test_no_key_uses_offline_and_says_so(self):
        client = DeepSeekClient(api_key="")
        result = planner.plan("board_a 跑 DFM-31", models=self.models, checks=self.checks, client=client)
        self.assertEqual(result.source, "fallback")
        self.assertTrue(any("DEEPSEEK_API_KEY" in w for w in result.warnings))

    def test_json_content_fallback_when_no_tool_call(self):
        reply = {"choices": [{"message": {"content": json.dumps(VALID, ensure_ascii=False)}}]}
        client, _ = client_with([(200, reply)])
        result = planner.plan("board_a 跑 DFM-31", models=self.models, checks=self.checks, client=client)
        self.assertEqual(result.source, "llm")


@unittest.skipUnless(
    os.environ.get("NXDRP_LIVE_LLM") == "1" and os.environ.get("DEEPSEEK_API_KEY"),
    "需要 NXDRP_LIVE_LLM=1 与 DEEPSEEK_API_KEY 才跑真实 DeepSeek",
)
class LiveDeepSeekTests(unittest.TestCase):
    """显式开启后才联网。CI 默认跳过，避免把外部服务的抖动算成代码缺陷。"""

    def test_live_plan(self):
        client = DeepSeekClient()
        result = planner.plan(
            "把 board_a 的电流改成 20 A，只看温升和 DFM-31",
            models=context.available_models(),
            checks=context.check_catalog(),
            client=client,
        )
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.spec.model.ref, "board_a")
        self.assertEqual(result.spec.simulation.scenario, "current_temp")


if __name__ == "__main__":
    unittest.main()
