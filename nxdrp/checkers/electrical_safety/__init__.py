# -*- coding: utf-8 -*-
"""电气安规检查（IEC 60664-1）——V2：宋馨雨、汪琪竣。"""

from .saf01_clearance import ClearanceChecker
from .saf02_creepage import CreepageChecker
from .saf03_compliance import SafetyComplianceChecker
from .saf04_suggestion import SafetySuggestionChecker

CHECKERS = [
    ClearanceChecker(),
    CreepageChecker(),
    SafetyComplianceChecker(),
    SafetySuggestionChecker(),
]

__all__ = [
    "ClearanceChecker",
    "CreepageChecker",
    "SafetyComplianceChecker",
    "SafetySuggestionChecker",
    "CHECKERS",
]
