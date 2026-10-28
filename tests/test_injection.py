# -*- coding: utf-8 -*-
"""让团队统一测试命令自动包含 注塑/铸造 DFM 回归测试（代世航）。"""

from nxdrp.checkers.injection.tests.test_injection import (  # noqa: F401
    TestDfm08MinWall,
    TestDfm09UniformWall,
    TestDfm10WallVariation,
    TestDfm11RibDesign,
    TestDfm12MoldWall,
    TestDfm13Draft,
    TestDfm14Undercut,
    TestDfm15Boss,
    TestDfm16Fillet,
    TestDfm17MultiPull,
    TestDfm18SharpCorner,
    TestRegistrationAndRules,
)
