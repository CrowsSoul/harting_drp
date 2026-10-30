# Check-Mate 规则取证（DFM 规则公式化）

本目录记录我们如何从 NX Check-Mate 提取**判定口径**（公式、限值、比较算子、边界、舍入），
以及每条规则与 Check-Mate 的对齐状态与置信度。

## 一、三条取证通道

| 通道 | 做法 | 产物 |
|---|---|---|
| ① 官方文档 | 读 NX 安装目录里的 Check-Mate 检查器帮助页（`DESIGN_TOOLS\checkmate\dfmadvisor\localization\*.html`）与 `.dfa` 规则文档段 | 参数名、默认值、判定描述 |
| ② 黑盒差分 | 用 `tools/checkmate/run_checkmate.py` 参数化跑 Check-Mate，解析 PLMXML 日志 | 样本 JSON（输入几何/参数 → 判定） |
| ③ 规则文件解析 | `tools/checkmate/extract_dfa.py` 只读解析 `.dfa`（KF 纯文本）的参数与比较结构 | 参数表、比较算子清单 |

三条通道互相对照：①给口径，②给行为，③补细节。**置信度**：

- **high**：文档 + 黑盒双证；
- **medium**：仅文档或仅规则文件；
- **low**：仅经验推断，待样本集补齐。

## 二、合规边界（组内约定）

只提取判定口径，不复制 Siemens 的代码、资源或数据文件：

- **入库**：我们自己写的公式表述、参数名与默认值、出处路径引用、我们自己造的试验数据与判定对照表；
- **不入库**：`.dfa` 原文、`Checkers.py`/`NXCheckers.json` 原始内容、产品示例源码、Check-Mate 日志与试验件 prt——统一放 `.local/`（已在 `.gitignore`）。

引用出处时写清文件路径与小节（如 `<参数节> ld_ratio_max`），不粘贴原文。

## 三、工具

```bash
# 解析一个 .dfa 的参数与比较结构（默认只输出结构化 JSON，不落盘）
python tools/checkmate/extract_dfa.py "<dfa 路径>"

# 跑 Check-Mate（黑盒）。默认跑官方示例 DeepHole.prt + 产品自带 dfms_DeepHoles
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles --param ld_ratio_max=30.0
```

样本默认写到 `.local/checkmate_results/`，日志在 `.local/checkmate_logs/`。

## 四、本目录文件

| 文件 | 内容 |
|---|---|
| `smoke.md` | 许可与环境冒烟结论（W1） |
| `DFM-27.md` ~ `DFM-38.md` | 机加工 12 条迁移规则的取证记录与差异清单（每条一份） |

规则模型与迁移方法见 [`../CHECKMATE_RULE_V2.md`](../CHECKMATE_RULE_V2.md)，
总体进度与已知问题见 [`../CHECKMATE_WORK_STATUS.md`](../CHECKMATE_WORK_STATUS.md)。

后续每个迁移批次（机加其余 9 项 → 注塑 → 钣金 → 装配）都按同一模板新增文件。
