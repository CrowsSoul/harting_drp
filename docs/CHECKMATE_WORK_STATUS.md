# Check-Mate 规则复刻 — 任务进度记录

> 分支：`feat/nx-checkmate-cae-rule-replication`（V2 主线 C 的 DFM 部分）
> 最近更新：2026-10-30（W1 + W2 完成：机加工 12 项全部迁移）

## 一、任务与范围

把 38 项 DFM 检查从"填参数、比阈值"升级为 NX Check-Mate 风格的**公式 + 比较规则**：
规则里写表达式、单位、舍入、例外与出处，checker 只保留几何测量；
再按新规则重构 DFM 检查插件（PERF 部分另线推进）。

本记录覆盖 **W1 + W2**：规则模型 v2 + 表达式引擎 + 机加工 12 项（DFM-27~38）全部迁移。

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
需要黑盒样本的项（DFM-28/32/37 等）在 W3 前后用参数化试验件补齐。

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
| W3 注塑 11 项 | `table()` 材料查表、容差模式；对照 `TOOLING_BASE\dfa\mw_check_*.dfa` 与 `dfms_MinimumDraftAngle` 等；顺带补机加黑盒试验件（`f_slot_sweep` 等） | W2 |
| W4 钣金 8 项 | 公式阈值（`3t + R` 类）；对照 `checkmate\dfa\checker\sheet_metal\mqc_dfm_*.dfa` | W3 |
| W5 装配 7 项 | 布尔/几何谓词；对照 `dfa\checker\assemblies` 与 `dfms_Fastener*` | W4 |

## 六、复现命令

```bash
# 单测
python -m unittest discover -s tests

# 双跑对账（13 个 mock 模型，零差异；机加 12 项全量）
python tools/checkmate/reconcile_verdicts.py --model mockdata/models \
    --no-expression-for DFM-27,DFM-28,DFM-29,DFM-30,DFM-31,DFM-32,DFM-33,DFM-34,DFM-35,DFM-36,DFM-37,DFM-38

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
