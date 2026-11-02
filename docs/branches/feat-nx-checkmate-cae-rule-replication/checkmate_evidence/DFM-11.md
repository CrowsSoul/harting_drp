# DFM-11 加强筋设计 — Check-Mate 取证

## 1. 出处

Check-Mate DFM Advisor **无加强筋检查器**；阈值为注塑工艺基线
（筋根厚/壁厚、筋高/根厚两个倍率）。

## 2. 判定口径（本项目基线）

- `root_ratio = 筋根厚 / 名义壁厚`；`height_ratio = 筋高 / 筋根厚`；
- `root_ratio > max_rib_root_to_wall_ratio` 或 `height_ratio > max_rib_height_to_root_ratio` → 报；
- 两者都超时，按旧路径以筋根厚指标作为 measured（expression cases 顺序即此语义）。

## 3. 我们的实现

规则 `R-DFM-11` 两个 case（首个命中生效），unit 修正为 **比值**（旧路径误标 mm，
见 `tests/test_expr_injection.py` 的 `KNOWN_UNIT_FIXES`）。

## 4. 差异清单

| 项 | 旧路径 | v2 | 说明 |
|---|---|---|---|
| unit | `mm`（默认值，误标） | `比值` | 比例量单位修正 |
| 判定 | 相同 | 相同 | 双跑零差异（unit 除外） |

## 5. 置信度

**low（对齐度）** —— 无 Check-Mate 对照项；倍率为项目基线。
