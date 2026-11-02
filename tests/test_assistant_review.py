# -*- coding: utf-8 -*-
"""AI 评测与 PDF 评测报告：规则结论、AI 输出、降级与文件头。"""

import json
import tempfile
import unittest
from pathlib import Path

from nxdrp.assistant import review
from nxdrp.assistant.report import build_report


def payload(**overrides):
    data = {
        "state": "completed",
        "spec": {
            "instruction": "把 board_a 的电流改成 20 A",
            "model": {"ref": "board_a"},
            "checks": {"only": ["PERF-01"], "rule_overrides": {"PERF-01": {"current_a": 20}}},
        },
        "model": {"model_id": "board_a"},
        "checks": {
            "findings": [
                {"finding_id": "F1", "check_item_id": "PERF-01", "check_item_name": "温升",
                 "severity": "P2", "message": "温升超限", "measured_value": 150.6,
                 "threshold_value": 45, "unit": "°C",
                 "suggestion": {"text": "把截面积加大到 6.74 mm²"}},
            ],
            "finding_count": 1,
        },
        "simulation": {
            "scenario": "current_temp", "engine": "性能模型（PERF-01）",
            "outputs": {"delta_t_c": 150.6, "delta_t_low_c": 141.7, "delta_t_high_c": 174.2,
                        "max_rise_c": 45, "alarm": True, "allowable_current_a": 10.93},
            "basis": "规则 R-PERF-01",
        },
        "summary": {"text": "摘要", "basis": ["PERF-01：集总模型"]},
    }
    data.update(overrides)
    return data


class ReviewTests(unittest.TestCase):
    def test_missing_geometry_is_not_a_pass_even_with_ai(self):
        class MustNotCall:
            def enabled(self): return True
            def chat(self, *args, **kwargs): raise AssertionError('must not override missing data')
        incomplete = payload(checks={'findings': [], 'executed': 0, 'total': 1,
                                    'results': [{'status': 'missing_data'}]},
                             simulation={'scenario': 'nx_parameters', 'changed': {'length': 35}})
        result = review.review(MustNotCall(), incomplete)
        self.assertEqual(result['verdict'], '待补充数据')
        self.assertIsNone(result['score'])
        self.assertTrue(result['metrics']['insufficient_data'])

    def test_rule_review_flags_alarm(self):
        result = review.rule_review(payload())
        self.assertEqual(result["source"], "rule")
        self.assertEqual(result["verdict"], "不通过")
        self.assertLessEqual(result["score"], 45)
        self.assertTrue(result["risks"])
        self.assertTrue(result["actions"])

    def test_rule_review_pass_when_clean(self):
        clean = payload(checks={"findings": [], "finding_count": 0}, simulation=None)
        result = review.rule_review(clean)
        self.assertEqual(result["verdict"], "通过")
        self.assertGreaterEqual(result["score"], 85)

    def test_ai_review_used_when_available(self):
        class Stub:
            def enabled(self):
                return True

            def chat(self, *args, **kwargs):
                return {"content": json.dumps({
                    "verdict": "不通过", "score": 32,
                    "summary": "20 A 下温升严重超限。",
                    "risks": ["载流截面不足"], "actions": ["加大截面积到 6.74 mm²"],
                }, ensure_ascii=False)}

        result = review.review(Stub(), payload())
        self.assertEqual(result["source"], "llm")
        self.assertEqual(result["verdict"], "不通过")
        self.assertIn("rule_fallback", result)

    def test_ai_review_failure_falls_back(self):
        class Broken:
            def enabled(self):
                return True

            def chat(self, *args, **kwargs):
                return {"content": "not json"}

        result = review.review(Broken(), payload())
        self.assertEqual(result["source"], "rule")
        self.assertIn("退回规则", result["note"])

    def test_pdf_report(self):
        with tempfile.TemporaryDirectory(prefix="assistant-report-") as tmp:
            target = Path(tmp) / "report.pdf"
            build_report(payload(), target)
            self.assertTrue(target.is_file())
            self.assertGreater(target.stat().st_size, 5000)
            self.assertTrue(target.read_bytes().startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
