# -*- coding: utf-8 -*-
"""Check-Mate 取证工具的单测：.dfa 解析、XML 日志解析、参数类型转换。

全部用自造的合成文本，不依赖本机 NX 安装。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.checkmate.extract_dfa import extract
from tools.checkmate.run_checkmate import _parse_value, parse_checkmate_xml

SAMPLE_DFA = """\
#! NX/KF 10.0
# DOCUMENTATION
#++
<Description>

    This checker checks example thickness.

</Description>

<Parameters>

    ************************* Range *************************

    ( Number )   minimum_thickness - Specifies the minimum thickness allowed.
                                    The default value is 1.

    ( Number )   maximum_thickness - Specifies the maximum thickness allowed.
                                    The default value is 10.

    ( Name )     log_type        - Specifies the log type.
                                    The default is LOG_ERROR.

</Parameters>

DefClass: example ( ug_base_checker );
(Any Uncached) do_check:
@{
    If $sheet_metal_thickness > $maximum_thickness
    Then mqc_log(LOG_ERROR, {}, "too thick");
    Else mqc_log(LOG_INFO, {}, "ok");
};
"""

SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<PLMXML xmlns="http://www.plmxml.org/Schemas/PLMXMLSchema"
        xmlns:chk="http://www.plmxml.org/Schemas/PLMXMLSchemaCheckMate">
  <chk:CheckReport>
    <chk:CheckPart name="Demo.prt" status="fail">
      <chk:Profile name="Session" status="fail">
        <chk:Checker class="dfms_DeepHoles" name="dfms_DeepHoles_1" status="fail">
          <chk:Parameters>
            <chk:Parameter title="ld_ratio_max" value="5"/>
            <chk:Parameter title="LogOption" value="&quot;LOG_ERROR&quot;"/>
          </chk:Parameters>
          <chk:CheckResult status="fail">
            <chk:CheckMessageInfo>Detected 1 areas as Failed.</chk:CheckMessageInfo>
            <chk:DetailSetInfo name="Hole: L = 95.0 mm, D = 3.5 mm" status="fail">
              <chk:CheckMessageInfo>Measurement result: L/D = 27.14 Error criteria: 5.0 &lt; L/D</chk:CheckMessageInfo>
            </chk:DetailSetInfo>
          </chk:CheckResult>
        </chk:Checker>
      </chk:Profile>
    </chk:CheckPart>
  </chk:CheckReport>
</PLMXML>
"""


class ExtractDfaTests(unittest.TestCase):
    def test_parameters_and_comparisons(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.dfa"
            path.write_text(SAMPLE_DFA, encoding="utf-8")
            result = extract(str(path))
        self.assertEqual(result["title"], "This checker checks example thickness.")
        by_name = {p["name"]: p for p in result["parameters"]}
        self.assertEqual(by_name["minimum_thickness"]["default"], "1")
        self.assertEqual(by_name["maximum_thickness"]["default"], "10")
        self.assertEqual(by_name["log_type"]["default"], "LOG_ERROR")
        self.assertTrue(result["do_check"]["present"])
        self.assertIn(">", result["do_check"]["comparison_ops"])
        self.assertIn("maximum_thickness", result["do_check"]["referenced_parameters"])


class ParseCheckmateXmlTests(unittest.TestCase):
    def test_structured_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.xml"
            path.write_text(SAMPLE_XML, encoding="utf-8")
            sample = parse_checkmate_xml(str(path))
        self.assertEqual(sample["checker"], "dfms_DeepHoles")
        self.assertEqual(sample["status"], "fail")
        self.assertEqual(sample["parameters"]["ld_ratio_max"], "5")
        self.assertEqual(sample["details"], [{"name": "Hole: L = 95.0 mm, D = 3.5 mm", "status": "fail"}])
        self.assertTrue(any("L/D = 27.14" in m for m in sample["messages"]))


class ParseValueTests(unittest.TestCase):
    def test_types(self):
        self.assertEqual(_parse_value("2.0"), 2.0)
        self.assertEqual(_parse_value("3"), 3)
        self.assertIs(_parse_value("true"), True)
        self.assertIs(_parse_value("FALSE"), False)
        self.assertEqual(_parse_value("[0,0,-1]"), [0, 0, -1])
        self.assertEqual(_parse_value("LOG_ERROR"), "LOG_ERROR")


if __name__ == "__main__":
    unittest.main()
