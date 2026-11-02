# Check-Mate 规则复刻 — 任务进度记录

> 分支：`feat/nx-checkmate-cae-rule-replication`（V2 主线 C 的 DFM 部分）
> 最近更新：2026-10-31（W1~W5 完成：**38/38 项 DFM 全部公式化**）

## 一、任务与范围

把 38 项 DFM 检查从"填参数、比阈值"升级为 NX Check-Mate 风格的**公式 + 比较规则**：
规则里写表达式、单位、舍入、例外与出处，checker 只保留几何测量；
再按新规则重构 DFM 检查插件（PERF 部分另线推进）。

本记录覆盖 **W1~W5**：规则模型 v2 + 表达式引擎 + 机加工 12 项（DFM-27~38）
+ 注塑 11 项（DFM-08~18）+ 钣金 8 项（DFM-19~26）+ 装配 7 项（DFM-01~07）
全部迁移（**38/38**）。

## 〇、本轮交付范围（2026-10-31 收尾）

**本轮完成（离线可交付）**：DFM 38/38 公式化与证据文档、双跑对账、单测；
PERF-01/02 公式驱动重构、Simcenter/FloEFD 离线链路、结果契约与认证门禁、文档。

**明确不在本轮范围（需现场/正式授权，后续补做）**：

1. DFM 与 Check-Mate 的试验件一致率 ≥95% 报告（目前仅 DFM-27 有真实黑盒样本）；
2. PERF CAE 正式认证（每项 ≥20 授权样本、中位误差 ≤5%、判定一致率 ≥95%、网格研究）。

**本轮收尾项**：移除 `schema_documents()` 重复 schema 键；统一 `exceptions` 契约为
`skip: true`（无 expression 的规则标 `enforced_by: "checker"`）；PERF 公式库与取证映射
补逐规则 `confidence_level`/`confidence_basis`。

## 二、W1 完成清单

| # | 工作项 | 状态 | 证据 |
|---|---|---|---|
| 1 | Rule 契约 v2（expression/unit/rounding/exceptions/reference） | ✅ | `nxdrp/contracts/core.py`；`tests/test_expr_rule_v2.py`（7 例） |
| 2 | 表达式引擎（受限 DSL、单位、函数、失败语义） | ✅ | `nxdrp/expr/`；`tests/test_expr_engine.py`（47 例） |
| 3 | CheckContext.evaluate 集成 + 舍入收口 | ✅ | `nxdrp/checkers/base.py`、`_machining_common.py` |
| 4 | DFM-27/28/33 双路径迁移 | ✅ | 三个 checker；`rules/dfm_default.json` v0.5；`tests/test_expr_machining.py`（8 例） |
| 5 | 取证工具（.dfa 解析、Check-Mate 黑盒、双跑对账） | ✅ | `tools/checkmate/`、`nxdrp/journals/checkmate_checker.py`；`tests/test_checkmate_tools.py` |
| 6 | 证据落库（出处/参数/样本/置信度） | ✅ | `docs/checkmate_evidence/`（README + smoke + 3 份规则证据） |
| 7 | Check-Mate 许可冒烟 | ✅ | `docs/checkmate_evidence/smoke.md` |
| 8 | gen_rules 增量语义（不覆盖人工调参） | ✅ | `tools/gen_rules.py`；重跑后规则库语义零变化 |
| 9 | 回归：13 个 mock 模型新旧双跑 | ✅ | 零差异（`tools/checkmate/reconcile_verdicts.py`） |
| 10 | 全量单测 | ✅（1 项环境性失败） | 377 项：376 通过 / 1 失败（见第四节） |

## 二·B W2 完成清单（机加其余 9 项）

| # | 工作项 | 状态 | 证据 |
|---|---|---|---|
| 11 | 引擎扩展 `nearest(list,x)`（到标准系列最近元） | ✅ | `nxdrp/expr/`；引擎单测 50 例 |
| 12 | DFM-29/30/31/32/34/35/36/37/38 双路径迁移 | ✅ | 9 个 checker；`rules/dfm_default.json` v0.6 |
| 13 | 9 份 Check-Mate 取证文档（公式/默认值/差异清单） | ✅ | `docs/checkmate_evidence/DFM-29~38.md` |
| 14 | 新增表达式语义单测（布尔型 case、nearest 参数覆盖、单位） | ✅ | `tests/test_expr_machining.py`（14 例） |
| 15 | 双跑对账（12 项全量） | ✅ | 13 个模型零差异；对账工具改为数值容差匹配（消除二次舍入假差异） |
| 16 | 全量单测 | ✅（1 项环境性失败） | 386 项：385 通过 / 1 失败（同第四节） |

## 二·C W3 完成清单（注塑 11 项）

| # | 工作项 | 状态 | 证据 |
|---|---|---|---|
| 17 | 引擎扩展：case 可省略 measured（布尔型判定） | ✅ | `nxdrp/expr/cases.py`；引擎单测 51 例 |
| 18 | DFM-08~18 双路径迁移（含 `table()` 材料查表、`if()` 选倍率） | ✅ | 11 个 checker；`rules/dfm_default.json` v0.7 |
| 19 | 11 份取证文档（Check-Mate 有/无对应项的差异清单） | ✅ | `docs/checkmate_evidence/DFM-08~18.md` |
| 20 | 注塑 v2 单测（新旧等价 33 个模型 + 语义断言） | ✅ | `tests/test_expr_injection.py`（8 例） |
| 21 | 双跑对账（注塑 11 项） | ✅ | 13 个 mock 模型零差异；DFM-11 单位修正单独记录 |
| 22 | 全量单测 | ✅（1 项环境性失败） | 395 项：394 通过 / 1 失败（同第四节） |

## 二·D W4 完成清单（钣金 8 项）

| # | 工作项 | 状态 | 证据 |
|---|---|---|---|
| 23 | DFM-19~26 双路径迁移（系数×料厚、3t+R 公式） | ✅ | 8 个 checker；`rules/dfm_default.json` v0.8 |
| 24 | 8 份取证文档（含与 `dfms_PunchedHole*` 的阈值对照） | ✅ | `docs/checkmate_evidence/DFM-19~26.md` |
| 25 | 钣金 v2 单测（新旧等价 14 个模型 + 语义断言） | ✅ | `tests/test_expr_sheet_metal.py`（6 例） |
| 26 | 双跑对账（钣金 8 项） | ✅ | bent_sheet + 13 个 mock 模型零差异 |
| 27 | 全量单测 | ✅（1 项环境性失败） | 401 项：400 通过 / 1 失败（同第四节） |

## 二·E W5 完成清单（装配 7 项）

| # | 工作项 | 状态 | 证据 |
|---|---|---|---|
| 28 | DFM-01~07 双路径迁移（体积/间隙/对齐/紧固件三类） | ✅ | 7 个 checker；`rules/dfm_default.json` v0.9 |
| 29 | 7 份取证文档（含 `dfms_Fastener*` / `HoleAlignment` 默认值对照） | ✅ | `docs/checkmate_evidence/DFM-01~07.md` |
| 30 | 装配 v2 单测（22 个合成模型 + 13 个 mock 新旧等价、精确/粗筛 severity） | ✅ | `tests/test_expr_assembly.py`（6 例） |
| 31 | 双跑对账（装配 7 项） | ✅ | 零差异 |
| 32 | 全量单测 | ✅（1 项环境性失败） | 407 项：406 通过 / 1 失败（同第四节） |
| 33 | **38/38 DFM 规则全部带 expression/unit/rounding/reference** | ✅ | 规则库 v0.9 |

## 三、关键结论

### 1. Check-Mate 黑盒通道成立

- 本机 NX `Designcenter2606` 的 DFM Advisor 检查器可直接经 `CheckerExecutor` 执行，
  参数可按名覆盖（类型敏感：float 必须传 float）；
- 判定结果落在 PLMXML 日志里，`tools/checkmate/run_checkmate.py` 已能解析成结构化样本；
- 详见 `docs/checkmate_evidence/smoke.md`。

### 2. 机加工 12 项取证结论

| 规则 | Check-Mate 口径 | 我方实现 | 置信度 |
|---|---|---|---|
| DFM-27 深孔 | `L/D > ld_ratio_max`（默认 5，严格大于） | 两级 `>4 → P2`、`>10 → P1` | high（文档+黑盒） |
| DFM-28 深窄槽 | `D/W > depth_width_ratio_max`（默认 4） | `>3 → P2` | medium（仅文档） |
| DFM-29 平底盲孔 | 盲孔平底即失败 | 同判据 | high |
| DFM-30 刀具可达性 | 铣削方向可见性 | 包络遮挡（包围盒粗筛） | low |
| DFM-31 刀具标准 | 孔径不在标准系列即失败（默认英制系列） | `nearest()` + ±0.05 容差 | medium |
| DFM-32 底部圆角一致性 | 底部圆角半径不一致即失败 | 圆角种类数超上限 | medium |
| DFM-33 顶部圆角 | `dfms_TopFillets`：入口面**有圆角即失败** | 顶区**缺圆角 / 圆角过小**为失败 | low（方向相反） |
| DFM-34 内部倒角 | 型腔底部有内倒角即失败 | 角度/尺寸不在标准系列才报 | low（取向不同） |
| DFM-35 深圆角转角 | `L/R > lr_ratio_max`（默认 10）或 R=0 | 绝对半径 `R < 0.5` | medium（公式不同） |
| DFM-36 角度铣削面 | 铣削轴与侧壁夹角 | 到标准角系列的最近元 | medium |
| DFM-37 窄通道 | `W < 2.0 mm` 或 `D/W > 10` | `W < 1.0 mm` | medium |
| DFM-38 孔进出刀面 | 入/出刀边非圆弧即失败 | 孔口面与孔轴夹角 > 5° | low（判据不同） |

差异清单已逐条写入各证据文档，**未擅自改动工艺阈值**——待工艺负责人确认。
需要黑盒样本的项（DFM-28/32/37 等）在后续用参数化试验件补齐。

### 2·B 注塑 11 项取证结论

| 规则 | Check-Mate 对应 | 我方实现 | 置信度 |
|---|---|---|---|
| DFM-08 最小壁厚 | **无** | 材料表查值 × 临界倍率（P1 升级） | low |
| DFM-09 均匀壁厚 | **无** | 偏离面积占比 > 25% | low |
| DFM-10 壁厚变化 | **无** | 相邻变化率 > 25% | low |
| DFM-11 加强筋 | **无** | 筋根/壁厚、筋高/根厚两级（单位修正为比值） | low |
| DFM-12 模具壁厚 | **无** | 特征中心距 − 外包半宽 | low |
| DFM-13 拔模角 | `dfms_MinimumDraftAngle`（腔 2°/芯 1°）+ `mw_check_draft_angle.dfa`（3°、cross 5°） | `< 0.5°`（容差可配） | medium |
| DFM-14 倒扣 | `dfms_UndercutDetection` + `mw_check_undercut_area.dfa` | 上游特征记录 + 深度门槛 | medium |
| DFM-15 凸台设计 | **无** | 四类问题取最不利 | low |
| DFM-16 圆角半径 | `dfms_StandardCornerRadius`（标准半径，口径参考） | 内/外倍率 × 名义壁厚 | low |
| DFM-17 多抽芯方向 | **无**（`draft_dirs` 概念相近） | 方向聚类数 > 1 | low |
| DFM-18 尖角 | `mqc_pdq_sharp_edge_angle.dfa`（0.5°） | 二面角 < 60°（容差可配） | medium |

注塑域在 Check-Mate DFM Advisor 中**大部分没有对应检查器**（壁厚/筋/凸台/抽芯方向），
已如实标注 low；有对应项的（拔模/倒扣/尖角）逐条记录差异，未擅自改阈值。

### 2·C 钣金 8 项取证结论

| 规则 | Check-Mate 对应 | 我方实现 | 置信度 |
|---|---|---|---|
| DFM-19 最小弯曲半径 | `mqc_dfm_check_bending_break_radius.dfa`（0.1t 标准倍数 ±10%） | `R < 0.5t` | medium（口径不同） |
| DFM-20 孔到边缘 | `dfms_PunchedHoleToPartEdge`（3T） | `gap < 1.5t` | medium |
| DFM-21 孔间距 | `dfms_PunchedHoleSpacing`（3T） | `clear < 2t` | medium |
| DFM-22 孔径与料厚比 | `dfms_MinimumHoleDiameter`（1T） | `d < 1t` | **high（一致）** |
| DFM-23 槽的最小宽度 | `dfms_MinimumHoleDiameter` + `mqc_dfm_check_cutout_size.dfa` | `width < 1.2t` | medium |
| DFM-24 折弯与切口距离 | `dfms_PunchedHoleToBend`（3T） | `clear < 3t + R` | medium |
| DFM-25 翻边高度 | `dfms_MinimumFlangeHeight`（3 mm 与 3T 双限） | `h < 3t + R` | medium |
| DFM-26 冲压凸台高度 | `dfms_EmbossmentMaximumDepth`（5T 上限） | `h/t ∈ [0.6, 1.5]` | low（差异大） |

钣金是 Check-Mate 覆盖最全的一域；DFM-22 公式与默认值完全一致，其余为阈值/测量差。

### 2·D 装配 7 项取证结论

| 规则 | Check-Mate 对应 | 我方实现 | 置信度 |
|---|---|---|---|
| DFM-01 干涉 | `dfms_ComponentInterference`（有干涉即失败） | 体积 > 0.01 mm³ | medium |
| DFM-02 最小间隙 | **无直接对应** | 精确/粗筛两档，0.3 mm | low |
| DFM-03 孔对齐 | `dfms_HoleAlignment`（1 mm 搜索、0 容差） | 0.1/0.1/1.0° | medium |
| DFM-04 孔/槽对齐 | `dfms_SlotToHoleAlignment`（0.01 mm / 0.1°） | 0.2 mm / 1.0° | medium |
| DFM-05 紧固件可达性 | `dfms_FastenerAccess`（头部 2 mm + 插入 2 mm） | 工具包络 Φ10×40 | low |
| DFM-06 紧固件间隙 | `dfms_FastenerClearance`（端部 1 mm / 通孔 0.1 mm） | 轴向/径向各 0.5 mm | medium |
| DFM-07 啮合长度 | `dfms_FastenerEngagement`（L/D ≥ 1.5） | 钢 1.0 / 软材料 1.5 | medium |

### 3. 回归结论

- 新旧双路径在 13 个 mock 模型上判定零差异（severity / measured / threshold / unit / part / face 全字段）；
- 唯一展示差异：三条规则的 `rounding=2` 使 measured 从 4 位小数变 2 位（规则声明的可审计变更）；
- 规则库从 v0.4 升到 v0.5，除三条迁移规则外语义零变化（已用脚本核对 HEAD 差异）。

## 四、已知问题

| 问题 | 说明 | 处置 |
|---|---|---|
| Web 并发用例在 D 盘失败 | `test_ten_concurrent_upload_submit_read_and_isolation`：D 盘 SQLite 单次 update ≈103 ms（C 盘 6 ms），10 并发任务超 15 s 判定超时 | **与本次改动无关**：干净 HEAD 工作树放 D 盘同样失败、C 盘通过；验收建议在 C 盘或 SSD 环境跑全量 |
| Check-Mate 自带 Python 示例检查器未注册 | `Examples_NXOpenPython_CheckDeepHoles` 需放用户目录 `application\` 才加载 | 不影响黑盒（产品自带 `dfms_*` 可用）；不复制其源码 |
| DFM-33 与 Check-Mate 判定方向相反 | NX 判"入口面带圆角"为失败；我方判"缺/小圆角" | 已列差异清单，待工艺拍板；一致率指标暂不适用本条 |

## 五、下一步（W2–W5）

| 阶段 | 内容 | 前置 |
|---|---|---|
| ~~W2 机加其余 9 项~~ | ✅ 已完成（2026-10-30）：`nearest()`、9 项迁移、9 份证据、零差异对账 | — |
| ~~W3 注塑 11 项~~ | ✅ 已完成（2026-10-31）：`table()`/`if()`/可选 measured、11 项迁移、11 份证据、零差异对账 | — |
| ~~W4 钣金 8 项~~ | ✅ 已完成（2026-10-31）：8 项迁移、8 份证据、零差异对账 | — |
| ~~W5 装配 7 项~~ | ✅ 已完成（2026-10-31）：7 项迁移、7 份证据、零差异对账 | — |
| **验收补强** | 参数化试验件批量跑 Check-Mate，补全各域黑盒样本与一致率报告；38 项差异清单交工艺确认 | 甲方现场 |
| PERF 线 | Simcenter 3D / FloEFD 电热与接触工况复刻（另线，见 CLAUDE.md 五·2） | 独立启动 |
| W5 装配 7 项 | 布尔/几何谓词；对照 `dfa\checker\assemblies` 与 `dfms_Fastener*` | W4 |

## 六、复现命令

```bash
# 单测
python -m unittest discover -s tests

# 双跑对账（13 个 mock 模型 + 钣金夹具，零差异；38 项全量）
ALL_DFM=$(python -c "print(','.join(f'DFM-{i:02d}' for i in range(1,39)))")
python tools/checkmate/reconcile_verdicts.py --model mockdata/models --model tests/fixtures/bent_sheet.model.json \
    --no-expression-for "$ALL_DFM"

# Check-Mate 冒烟（fail / pass 两例）
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles --param ld_ratio_max=30.0

# 解析 .dfa 参数与比较结构
python tools/checkmate/extract_dfa.py "<NX>\DESIGN_TOOLS\checkmate\dfa\checker\sheet_metal\mqc_dfm_check_sheet_metal_thickness.dfa"
```

## 七、合规说明

- 入库的只有：自写代码、自写公式与参数表、出处路径引用、自造样本；
- Siemens 的 `.dfa` 原文、`Checkers.py`/`NXCheckers.json`、示例源码、Check-Mate 日志与试验件
  一律不入库，统一放 `.local/`（已加入 `.gitignore`）；
- 引用出处采用"文件路径 + 小节名"的方式，不粘贴原文。
