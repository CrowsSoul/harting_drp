# -*- coding: utf-8 -*-
"""让团队统一测试命令自动包含 装配 DFM 回归测试。"""

from nxdrp.checkers.assembly.test_assembly import (  # noqa: F401
    AlignmentTests,
    ClearanceTests,
    FastenerTests,
    InterferenceTests,
    RegistryTests,
    SceneAcceptanceTests,
)
