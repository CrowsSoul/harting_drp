# -*- coding: utf-8 -*-
"""让团队统一测试命令自动包含 Web 平台回归测试（陈卉妍）。

平台 后端依赖 fastapi / httpx（见 nxdrp/checkers/platform_web/requirements.txt）。
没装这些依赖时跳过本文件，其余模块的测试照常跑。
"""

import unittest

try:
    from fastapi.testclient import TestClient  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover - 取决于本机环境
    raise unittest.SkipTest(
        "平台 测试需要第三方依赖（fastapi/httpx）："
        "python -m pip install -r nxdrp/checkers/platform_web/requirements.txt"
    ) from exc

from nxdrp.checkers.platform_web.tests.test_web import WebTests  # noqa: E402,F401
