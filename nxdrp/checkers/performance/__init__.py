# -*- coding: utf-8 -*-
"""性能预测 —— 负责人：杜滨芳。

PERF-01 载流–温升和 PERF-02 插拔力均由规则公式驱动。已收敛的
NX/Simcenter/FloEFD 结果可通过结果契约覆盖公式输出；树模型只标定区间。
"""

from .perf01_current_temp import CurrentTempChecker
from .perf02_insertion_force import InsertionForceChecker

CHECKERS = [CurrentTempChecker(), InsertionForceChecker()]
