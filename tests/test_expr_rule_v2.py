# -*- coding: utf-8 -*-
"""规则模型 v2：Rule 新字段的往返兼容与 RuleBook 加载期校验。"""

from __future__ import annotations

import os
import unittest

from nxdrp.contracts import Rule, RuleBook
from nxdrp.errors import ContractError

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules", "dfm_default.json")


class RuleV2FieldsTests(unittest.TestCase):
    def test_round_trip_preserves_v2_fields(self):
        rule = Rule(
            rule_id="R-TEST-01",
            check_item_id="TEST-01",
            expression={"cases": [{"when": "meas.a > params.b", "measured": "meas.a",
                                   "threshold": "params.b"}]},
            unit="mm",
            rounding=2,
            exceptions=[{"when": "meas.exempt == 1", "skip": True}],
            reference="checkmate\\dfa\\example.dfa",
        )
        again = Rule.from_dict(rule.to_dict())
        self.assertEqual(again.expression, rule.expression)
        self.assertEqual(again.unit, "mm")
        self.assertEqual(again.rounding, 2)
        self.assertEqual(again.exceptions, rule.exceptions)
        self.assertEqual(again.reference, rule.reference)
        self.assertTrue(again.has_expression)

    def test_old_rule_dict_still_loads(self):
        rule = Rule.from_dict({"rule_id": "R-OLD", "check_item_id": "OLD-01", "params": {"x": 1}})
        self.assertEqual(rule.params, {"x": 1})
        self.assertEqual(rule.expression, {})
        self.assertIsNone(rule.rounding)
        self.assertEqual(rule.exceptions, [])
        self.assertEqual(rule.reference, "")
        self.assertFalse(rule.has_expression)

    def test_has_expression_requires_cases(self):
        self.assertFalse(Rule(rule_id="a", check_item_id="b", expression={}).has_expression)
        self.assertFalse(Rule(rule_id="a", check_item_id="b", expression={"cases": []}).has_expression)
        self.assertTrue(
            Rule(rule_id="a", check_item_id="b",
                 expression={"cases": [{"when": "1 > 0"}]}).has_expression
        )


class RuleBookValidateTests(unittest.TestCase):
    def test_good_expression_passes(self):
        book = RuleBook(rules=[Rule(
            rule_id="R-1", check_item_id="C-1",
            expression={"cases": [{"when": "meas.ratio > params.limit",
                                   "measured": "meas.ratio", "threshold": "params.limit"}]},
        )])
        book.validate()  # 不抛异常

    def test_bad_expression_rejected_at_load(self):
        book = RuleBook(rules=[Rule(
            rule_id="R-1", check_item_id="C-1",
            expression={"cases": [{"when": "meas.ratio >", "measured": "meas.ratio"}]},
        )])
        with self.assertRaises(ContractError) as caught:
            book.validate()
        self.assertIn("C-1", str(caught.exception))

    def test_bad_exception_rejected(self):
        book = RuleBook(rules=[Rule(
            rule_id="R-1", check_item_id="C-1",
            expression={"cases": [{"when": "1 > 0", "measured": "1"}]},
            exceptions=[{"when": "meas.x >"}],
        )])
        with self.assertRaises(ContractError):
            book.validate()

    def test_repo_rulebook_still_validates(self):
        book = RuleBook.load(RULES_PATH)
        book.validate()  # 现有规则库必须继续通过


if __name__ == "__main__":
    unittest.main()
