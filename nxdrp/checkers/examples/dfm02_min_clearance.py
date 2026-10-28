# -*- coding: utf-8 -*-
"""DFM-02 兼容入口。

历史参考实现曾放在 examples 中。正式实现已归入汪琪竣负责的 装配 包；保留本模块
只为兼容旧导入路径，并让注册器在既定扫描顺序下加载同一个实现。
"""

from ..assembly.dfm02_min_clearance import MinClearanceChecker


CHECKERS = [MinClearanceChecker()]
