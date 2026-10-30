# -*- coding: utf-8 -*-
"""从 catalog.py 生成规则库骨架。

规则库是「数据」，checker 是「算法」。新增检查项时先跑这个脚本拿到一条空规则，
填上 params，再写 checker —— 顺序反过来会导致阈值散落在代码里，违反合同第 7 条
（工程师要能免编程维护规则）。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp import catalog  # noqa: E402
from nxdrp.contracts import Rule, RuleBook  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(ROOT, "rules")

#: 默认严重度：安全与干涉最高，其余按提示级别起步，由工艺工程师后续调整
SEVERITY_OVERRIDE = {
    "SAF-01": "P0",
    "SAF-02": "P0",
    "SAF-03": "P1",
    "DFM-01": "P1",
    "DFM-05": "P1",
    "DFM-08": "P1",
    "DFM-13": "P1",
    "DFM-27": "P2",
}

#: 每个检查项的参数骨架（键名先占位，值由工艺工程师按甲方标准填写）
PARAM_SKELETON = {
    "DFM-01": {"interference_volume_mm3": 0.01, "critical_gap_mm": 0.05, "ignore_face_area_below_mm2": 0.1},
    "DFM-02": {"min_clearance_mm": 0.3},
    "DFM-05": {"tool_envelope_diameter_mm": 10.0, "tool_envelope_height_mm": 40.0},
    "DFM-06": {"axial_clearance_mm": 0.5, "radial_clearance_mm": 0.5},
    "DFM-07": {"engagement_ratio_steel": 1.0, "engagement_ratio_plastic": 1.5},
    "DFM-08": {"material": "PA66", "min_wall_thickness_mm": 0.8},
    "DFM-09": {"uniform_ratio_low": 0.8, "uniform_ratio_high": 1.25, "max_area_ratio": 0.1},
    "DFM-13": {"pull_direction": [0, 0, 1], "min_draft_angle_deg": 0.5},
    "DFM-16": {"inner_radius_ratio": 0.25, "outer_radius_ratio": 0.5},
    "DFM-18": {"sharp_angle_deg": 60.0},
    "DFM-19": {"min_bend_radius_ratio": 0.5, "sheet_thickness_mm": None},
    "DFM-20": {"min_edge_distance_ratio": 1.5, "sheet_thickness_mm": None},
    "DFM-21": {"min_hole_spacing_ratio": 2.0, "sheet_thickness_mm": None},
    "DFM-22": {"min_hole_diameter_ratio": 1.0, "sheet_thickness_mm": None},
    "DFM-23": {"min_slot_width_ratio": 1.2, "sheet_thickness_mm": None},
    "DFM-24": {"bend_clearance_ratio": 3.0, "bend_radius_override_mm": None,
               "sheet_thickness_mm": None},
    "DFM-25": {"min_flange_height_ratio": 3.0, "bend_radius_override_mm": None,
               "sheet_thickness_mm": None},
    "DFM-26": {"min_boss_height_ratio": 0.6, "max_boss_height_ratio": 1.5,
               "sheet_thickness_mm": None},
    "DFM-27": {"deep_hole_ratio": 4.0, "very_deep_hole_ratio": 10.0,
               "min_hole_diameter_mm": 0.5, "max_hole_diameter_mm": 50.0},
    "DFM-28": {"deep_slot_ratio": 3.0},
    "DFM-30": {"tool_clearance_mm": 2.0, "envelope_length_mm": 40.0},
    "DFM-31": {
        "standard_diameters": [1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0,
                               6.5, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 16.0, 18.0, 20.0],
        "tolerance_mm": 0.05,
        "max_hole_diameter_mm": 20.0,
        "min_hole_diameter_mm": 0.5,
    },
    "DFM-32": {"max_distinct_radii": 3, "cluster_tolerance_mm": 0.1, "min_radius_mm": 0.2},
    "DFM-33": {"min_top_fillet_mm": 0.5, "top_region_ratio": 0.75,
               "up_direction": [0.0, 0.0, 1.0]},
    "DFM-34": {"angle_tolerance_deg": 5.0, "size_tolerance_mm": 0.1},
    "DFM-35": {"min_corner_radius_mm": 0.5},
    "DFM-36": {"angle_tolerance_deg": 1.0, "min_face_area_mm2": 1.0},
    "DFM-37": {"min_channel_width_mm": 1.0},
    "DFM-38": {"max_entry_angle_deg": 5.0},
    "SAF-01": {"rated_voltage_v": 400, "pollution_degree": 2, "material_group": "II", "overvoltage_category": "III"},
    "SAF-02": {"rated_voltage_v": 400, "pollution_degree": 2, "material_group": "II", "cti": 600},
    "SAF-TOOL": {"tool": "AutoCrear", "tool_exe": "", "tool_timeout_s": 600, "result_format": "auto"},
    "SAF-03": {"combine": "worst"},
    "SAF-04": {"target_margin_mm": 0.5},
    "PERF-01": {
        "current_a": 16.0,
        "ambient_temp_c": 25.0,
        "interval_confidence": 0.8,
        "max_rise_c": 45.0,
        "convection_h_w_m2k": 15.0,
        "area_mm2_min": 0.5,
        "area_mm2_max": 20.0,
        "length_mm_min": 5.0,
        "length_mm_max": 40.0,
        "current_a_min": 1.0,
        "current_a_max": 40.0,
        "ambient_temp_c_min": 0.0,
        "ambient_temp_c_max": 80.0,
        "h_w_m2k_min": 8.0,
        "h_w_m2k_max": 25.0,
        "materials": {
            "Cu": {"rho_ohm_m": 1.724e-8},
            "CuSn6": {"rho_ohm_m": 1.3e-7},
            "CuZn37": {"rho_ohm_m": 6.2e-8},
            "CuBe2": {"rho_ohm_m": 7.8e-8},
        },
    },
    "PERF-02": {
        "contacts": 4.0,
        "lead_angle_deg": 30.0,
        "friction_coeff": 0.2,
        "overlap_mm": 0.2,
        "length_mm_min": 6.0,
        "length_mm_max": 15.0,
        "width_mm_min": 1.0,
        "width_mm_max": 4.0,
        "thickness_mm_min": 0.2,
        "thickness_mm_max": 0.6,
        "overlap_mm_min": 0.1,
        "overlap_mm_max": 0.5,
        "friction_min": 0.12,
        "friction_max": 0.3,
        "interval_confidence": 0.8,
        "insertion_force_max_n": 20.0,
        "withdrawal_force_min_n": 1.0,
        "materials": {
            "CuSn6": {"e_gpa": 110.0},
            "CuBe2": {"e_gpa": 131.0},
            "CuZn37": {"e_gpa": 100.0},
        },
    },
}


def build() -> RuleBook:
    rules = []
    for item in catalog.CATALOG:
        rules.append(
            Rule(
                rule_id=f"R-{item.check_item_id}",
                check_item_id=item.check_item_id,
                process_type=item.process_type,
                name=item.name_cn,
                enabled=True,
                params=PARAM_SKELETON.get(item.check_item_id, {}),
                version="0.1",
                source_standard="",
                severity=SEVERITY_OVERRIDE.get(item.check_item_id, "P2"),
                notes=item.hint,
                owner=f"{item.owner_module}",
            )
        )
    return RuleBook(
        name="dfm_default",
        version="0.1",
        updated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        rules=rules,
    )


def _merge(existing: RuleBook, generated: RuleBook) -> RuleBook:
    """增量补骨架：已有规则原样保留（params/expression/unit/rounding/... 人工修订），
    只为 catalog 里新增、规则库里还没有的检查项追加骨架。"""
    known = existing.by_item()
    rules = []
    added = []
    for rule in generated.rules:
        keep = known.get(rule.check_item_id)
        if keep is not None:
            rules.append(keep)
        else:
            rule.version = existing.version       # 新骨架跟随规则库版本，不写死 0.1
            rules.append(rule)
            added.append(rule.check_item_id)
    merged = RuleBook(
        name=existing.name or generated.name,
        version=existing.version,
        updated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        rules=rules,
    )
    return merged, added


def drift_report(existing: RuleBook) -> list[str]:
    """参数骨架与规则库的分叉提示（只提示，不修改）。"""
    lines = []
    for item in catalog.CATALOG:
        skeleton = PARAM_SKELETON.get(item.check_item_id)
        rule = existing.get(item.check_item_id)
        if skeleton is None or rule is None:
            continue
        extra = sorted(set(rule.params) - set(skeleton))
        missing = sorted(set(skeleton) - set(rule.params))
        if extra:
            lines.append(f"{item.check_item_id}: JSON 有而 SKELETON 无的键 {extra}")
        if missing:
            lines.append(f"{item.check_item_id}: SKELETON 有而 JSON 无的键 {missing}")
    return lines


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="生成/补全规则库骨架（默认增量，不覆盖人工调参）")
    parser.add_argument("--path", default=os.path.join(RULES_DIR, "dfm_default.json"))
    parser.add_argument("--force", action="store_true", help="整本重写（会覆盖人工调参，先打印将被覆盖的规则）")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = parser.parse_args(argv)

    os.makedirs(RULES_DIR, exist_ok=True)
    generated = build()
    book = generated
    added: list[str] = []
    if os.path.isfile(args.path):
        existing = RuleBook.load(args.path)
        if args.force:
            print("--force：以下规则的现有内容将被覆盖：")
            for rule in generated.rules:
                old = existing.get(rule.check_item_id)
                if old is not None and old.to_dict() != rule.to_dict():
                    print(f"  {rule.check_item_id}")
        else:
            book, added = _merge(existing, generated)
        drift = drift_report(existing)
        if drift:
            print("参数骨架分叉提示（仅提示，请人工同步 PARAM_SKELETON）：")
            for line in drift:
                print(f"  {line}")

    if args.dry_run:
        print(f"[dry-run] 将写出 {args.path}，规则 {len(book.rules)} 条，新增骨架 {added or '无'}")
        return 0
    book.save(args.path)
    book.validate()
    print(f"已写出 {args.path}（版本 {book.version}）")
    print(f"  规则条数: {len(book.rules)}；本次新增骨架: {added or '无'}")
    for mod, items in sorted(
        ((m, [i for i in catalog.CATALOG if i.owner_module == m]) for m in {i.owner_module for i in catalog.CATALOG})
    ):
        print(f"  {mod}: {len(items)} 项")


if __name__ == "__main__":
    main()
