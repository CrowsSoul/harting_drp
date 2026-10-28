# 连接器 AI 智能设计检查平台

一句话：把连接器的 3D 模型丢进去，自动查出设计问题，出一份能直接拿去评审的报告。

- 甲方：浩亭（珠海）制造有限公司
- 乙方：哈尔滨工业大学计算学部
- 当前版本：框架 v0.1.0，数据契约 v1.0.0，规则库 v0.4
- **合并版状态：8 个模块全部合入，44 / 44 检查项有实现，312 项测试全绿（缺可选依赖时为 303 项 + 4 项跳过）**

> 本目录是统一工程，44 / 44 检查项全部可运行，312 项测试全绿。
> 各模块的归属与第二轮分工见 [`docs/TEAM_TASKS.md`](docs/TEAM_TASKS.md) 与 [`docs/V2_PLAN.md`](docs/V2_PLAN.md)。

---

## 一、这个平台要解决什么

浩亭的工程师现在怎么干活：

- 连接器设计完，要在 NX 里**逐项人工点** 38 项可制造性检查（DFM），一个人一下午，还容易漏；
- 电气间隙、爬电距离要手工操作 AutoCrear 量，靠经验判断；
- 载流、温升、插拔力这些性能，只能靠算、靠经验、靠试做样品。

一条产品走完，光检查就是 1~2 个工作日，性能验证还要 5 天。

平台要做的事：**模型上传 → 自动跑完全部检查 → 出一份报告**。报告里每条问题都要说清四件事——在哪儿、差多少、多严重、怎么改。

本期（12 个月）落地的三件事：

| 做什么 | 做到什么程度 |
|---|---|
| 智能 DFM 检查 | 38 个检查项，缺陷识别准确率 ≥ 90% |
| 智能安规检查 | 电气间隙 + 爬电距离，精度不低于 AutoCrear |
| 智能性能预测 | 选一项（建议载流–温升）做 AI 预测 |

外加两条硬指标：**单次完整检查 ≤ 30 分钟**、**支持 10 人并发**。

---

## 二、你在其中做什么

8 个人分 8 块，你负责其中一块。先看 [`docs/TEAM_TASKS.md`](docs/TEAM_TASKS.md) 找到你自己。

简单说：**平台骨架和标准已经搭好了，你往里面填检查项**。填一个检查项大约几十行代码，不用碰框架的其他部分。

---

## 三、一条缺陷是怎么被查出来的

这一节理解了，后面所有术语都能对上号。

假设工程师上传一个外壳模型，想知道壁厚够不够。

1. **读模型** — NX 把 `.prt` 拆开：3 个零件、32 个面，每个面的面积、半径、位置、包围盒都量出来。
2. **装进一个盒子** — 这些数字存成一个 JSON，叫 `ModelBundle`。**同一个模型只解析一次**，后面几十个检查项都读这一份，不再碰 NX。
3. **逐条规则去查** — 每个检查项对应一个 checker（就是一段代码）。最小壁厚那个 checker 从盒子里挑出所有平面，量出厚度，跟规则里的 0.8 mm 比。
4. **吐出统一格式的记录** — 薄了的地方变成一条 `Finding`：零件 P01、面 F40181、实测 0.62 mm、阈值 0.8 mm、差 −0.18 mm、建议加厚到 0.8。
5. **拼成报告** — 报告模块把所有 Finding 按检查项分组，配上 3D 定位图，导出 Word/PDF。

**你要写的，就是第 3 步里的那一个 checker。** 第 1、2 步是框架做的，第 4、5 步的格式也已经定好了，你照着填就行。

---

## 四、六个词，认识就够了

| 术语 | 大白话 | 你什么时候会碰到 |
|---|---|---|
| `ModelBundle` | 一个 JSON，装着模型的所有几何数据 | 你的 checker 从这里取面、取零件 |
| checker | 一个检查项的实现，就是一个类 | **你要写的** |
| `Finding` | 查出来的一条问题记录 | 你的 checker 产出它 |
| 规则库（`rules/*.json`） | 阈值配置表，多少算合格写这里 | 调阈值时改它，不用改代码 |
| 管线（pipeline） | 调度器，把注册好的 checker 挨个跑一遍 | 一般不用管 |
| 注册表（registry） | 自动发现"谁写了 checker"的名单 | 你导出 `CHECKERS` 就自动登记 |

其余名词（IEC 60664-1、爬电距离、拔模角……）在你自己那份任务说明里有解释。

---

## 五、三分钟跑起来

要求：**Python 3.12+**。核心检查器零第三方依赖，没装 NX 也能开发；
只有 Web 平台、报告两个模块要装可选项。

本交付包已经把 Python 3.12.14 放在 `.python\`、把平台与报告的依赖放在 `.venv\`，
双击 `启动平台.cmd` 就能用，**这台机器不需要另装 Python、也不需要联网**；
自己敲命令时把下面的 `python` 换成 `.venv\Scripts\python.exe` 即可。

```powershell
cd harting_drp_merged

# 0) 可选：装平台与报告需要的包（不装也能跑检查与大部分测试）
python -m pip install -r requirements.txt

# 1) 体检：NX 在不在、插件能加载几个
python -m nxdrp doctor

# 2) 自检：契约 + 插件 + 管线 + Mock 全链路
python -m nxdrp selftest

# 3) 用 Mock 模型跑一次完整检查
python -m nxdrp check mockdata/models/board_a.model.json -r rules/dfm_default.json
```

合并版在 board_a 上跑完是 7 条 finding（DFM-02 / DFM-20 / DFM-22 / DFM-31×2 / DFM-32 / PERF-01）：
电气安规、性能预测 合入后比原来 6 条多了 PERF-01 的温升超限。

装了 NX 的机器再跑第 4 步（本机已用 NX 2606 实测：`mockdata/parts/plate_holes.prt` 解析 31 s，
结果与仓库里的 `plate_holes.model.json` 逐条一致）：

```powershell
python -m nxdrp extract "C:\path\to\housing.prt" -o housing.model.json
```

首次约 30 秒（NX 要启动），之后走缓存，几十毫秒。

**跑测试**：`python -m unittest discover -s tests` →
装了可选依赖 312 项全过；没装时 303 项通过、4 项跳过（平台、平台-报告 联调、报告 导出两条），零失败。

**启动 Web 平台**：双击 `启动平台.cmd`。它用包内自带的 `.venv`（基座 `.python\python.exe`）起服务，
自动避开被占用的端口，等 `/api/health` 正常后自动打开浏览器，窗口里也会打印地址。
想固定端口用 `启动平台.cmd 8010`（等价于 `python -m nxdrp.checkers.platform_web --port 8010`）。
脚本已设好 `NXDRP_REPORT_PROVIDER=nxdrp.checkers.report:generate_report`，报告页可直接下载 Word / PDF。

**单独启动 报告台**：双击 `启动报告台.cmd`，浏览器打开 http://127.0.0.1:8768 。

---

## 六、目录结构

```
harting_drp/
├── nxdrp/                      框架本体
│   ├── contracts/core.py       三份数据契约的定义
│   ├── catalog.py              44 个检查项的总目录
│   ├── checkers/base.py        所有 checker 继承的 BaseChecker
│   ├── checkers/examples/      3 个参考实现（DFM-02 / DFM-31 / DFM-32）
│   ├── checkers/electrical_safety/    电气安规（宋馨雨）
│   ├── checkers/injection/            注塑/铸造（代世航）
│   ├── checkers/assembly/             装配（汪琪竣）
│   ├── checkers/performance/          性能预测（杜滨芳）
│   ├── checkers/sheet_metal/          钣金（于大淇）
│   ├── checkers/machining/            机加工（张百瑞）
│   ├── checkers/platform_web/         Web 平台（陈卉妍）
│   ├── checkers/report/               报告与知识库（赵文哲）
│   ├── checkers/eval/          评测框架：标注集 → 匹配 → P/R/F1
│   ├── registry.py             插件发现
│   ├── pipeline.py             调度
│   ├── adapters/nx_batch.py    调本机 NX
│   └── journals/               在 NX 里跑的小脚本
├── rules/
│   ├── dfm_default.json        44 条规则的阈值（v0.4）
│   ├── iec_60664_1_profiles.json  IEC 60664-1 限值表（电气安规用）
│   └── tool_library.json       标准刀具库（机加工用）
├── mockdata/
│   ├── models/                 三套评测场景 + Mock + 2 个真实 NX 零件
│   ├── labels/                 标注集（评测用）
│   └── scenes/                 场景的 .prt 原文件
├── tests/                      312 个单元测试
├── tools/                      生成骨架 / 规则 / Mock / 看板的小工具
├── contracts/schema/           三份 JSON Schema
└── docs/                       文档与运行截图
```

进到自己的 checker 子包后先看那里的 `README.md`，写明了这个包负责哪几项、先做哪件。

---

## 七、常用命令

| 想干什么 | 命令 |
|---|---|
| 查我负责哪几项 | `python -m nxdrp items --owner 注塑` |
| 看我写的 checker 有没有被认出来 | `python -m nxdrp checkers` |
| 只跑我这一项，快 | `python -m nxdrp check 模型.json --only DFM-31` |
| 跑全量并出结果文件 | `python -m nxdrp check 模型.json -o out.json` |
| **给结果打分** | `python -m nxdrp eval out.json -l 标注集.json` |
| 解析一个新模型 | `python -m nxdrp extract a.prt -o a.json` |
| 跑测试 | `python -m unittest discover -s tests` |

---

## 八、现在有什么，还缺什么

**已经能用的，都在真模型上验证过**

| 能力 | 状态 |
|---|---|
| 调本机 NX 2606 读模型 | 3 个 NX 自带样例解析成功 |
| 几何数据提取（零件 / 面 / 边 / 面积 / 半径 / 包围盒 / 邻接） | 已验证 |
| **面法向 + 圆柱轴线**（拔模角、倒扣、转角类检查的前提） | Pressure Port 实测 13 个面（2 平面 / 7 B 曲面 / 3 圆柱 / 1 球面）全部带法向或轴向 |
| **批量精确测距**（`measure_distance`，一次 NX 启动测完所有配对） | 实测两对面：27.73 mm / 2.65 mm；无效 tag 优雅报错 |
| **装配结构解析**（组件展开 + 变换矩阵 + 装配坐标系） | 自建两零件装配实测：PART_B 位移 x=120 正确读出 |
| **三套评测场景**（混合 / 纯负样本 / 阈值边界） | `demo_asm` 6 组件 78 面出 5+18 条；`demo_normal` 零误报；`demo_edge` 只报 0.299 与 0.300，0.302 正确跳过 |
| **边长度 + 曲线类型** | demo_asm 114 条边全部带长度（13.98–30.32 mm），类型 72 直线 / 42 圆弧 |
| **精确测距代理**（NxDistanceProxy） | 批量预取 + 缓存，7 个单测；checker 不再逐对起 NX |
| **性能实测** | 312 面 33.5 s、检查 0.28 s；边际 5.6 ms/面（见 docs/PERF.md） |
| **评测框架**（标注集 → P/R/F1、macro-F1、高危项召回、误报率） | 三套场景共 32 条标注跑通，21 个单测覆盖 |
| 三份契约 + 校验 | 已验证 |
| 插件机制（内置目录 / 任意外部目录） | 外部放一个文件就能生效 |
| 检查管线（过滤、跳过、异常隔离、覆盖率） | 已验证 |
| **44 / 44 检查项有实现** | `python -m nxdrp checkers` 见 8 个模块全部注册 |
| **13 个 Mock 模型跑通** | 0 个 checker 异常，缺数据一律 skipped / missing_data 并写明原因 |
| **Web 主流程** | 上传 → 任务 → 进度 → 结果 → HTML/Word/PDF 报告，10 并发单测通过 |
| **报告** | 44 项索引、Word/PDF/HTML/ZIP、3D 定位图、44 项整改模板、归档与检索 |
| 不装 NX、用 Mock 数据开发 | 已验证 |

**还缺的**

| 缺什么 | 影响 | 谁补 |
|---|---|---|
| 标注集只有格式样例，没有人工标注 | 90% 准确率现在能算，但算的不是真数 | 工艺 + 8 个人边做边标 |
| 现场 NX 真实模型联调 | 本机 NX 2606 已验证解析链路，但验收模型、截图与面编号仍需现场确认 | 现场验收 |
| AutoCrear 对照基准 | 电气安规 的对照脚本已就绪（`autocrear_compare.py`），但本机未装 AutoCrear，缺基准数据 | 电气安规 + 甲方 |
| 10 并发 / 30 分钟指标 | 单测层面通过，需在验收环境压测 | 验收前 |

---

## 九、八个人，八块，现在都合进来了

| # | 姓名 | 模块 | 目录 | 检查项 | 状态 |
|---|---|---|---|---|---|
| 1 | 宋馨雨 | 电气安规 智能安规 | `nxdrp/checkers/electrical_safety/` | SAF-01 ~ SAF-04 | 4/4，含自研爬电与 IEC 限值表 |
| 2 | 于大淇 | 钣金 DFM | `nxdrp/checkers/sheet_metal/` | DFM-19 ~ DFM-26 | 8/8 |
| 3 | 代世航 | 注塑 / 铸造 DFM | `nxdrp/checkers/injection/` | DFM-08 ~ DFM-18 | 11/11 |
| 4 | 汪琪竣 | 装配 DFM | `nxdrp/checkers/assembly/` | DFM-01 ~ DFM-07 | 7/7 |
| 5 | 杜滨芳 | 性能预测 | `nxdrp/checkers/performance/` | PERF-01, PERF-02 | 2/2，含训练/推理/模型卡 |
| 6 | 张百瑞 | 机加工 DFM | `nxdrp/checkers/machining/` | DFM-27 ~ DFM-38 | 12/12 |
| 7 | 陈卉妍 | Web 平台 | `nxdrp/checkers/platform_web/` | — | 主流程 + 并发 + 规则版本 |
| 8 | 赵文哲 | 报告与知识库 | `nxdrp/checkers/report/` | — | 44 项报告 + 三种导出 |

张百瑞那份独立插件包（源码 + 独立测试 + 校验标注）原样放在 `contrib/machining_plugin/`，
作为合并前的原始交付留档；框架只加载 `nxdrp/checkers/`，不会重复注册。

---

## 十、遇到问题查哪份文档

| 情况 | 看这份 |
|---|---|
| **怎么用界面跑完整个流程（带截图）** | [`运行说明.md`](运行说明.md) |
| **合并了什么、验证到哪一步、还有哪些坑** | [`合并说明.md`](合并说明.md) |
| 不知道自己该干什么 | [`docs/TEAM_TASKS.md`](docs/TEAM_TASKS.md) |
| 想写第一个 checker | [`docs/HOW_TO_ADD_A_CHECKER.md`](docs/HOW_TO_ADD_A_CHECKER.md) |
| 想查数据里有哪些字段 | [`docs/CONTRACT.md`](docs/CONTRACT.md) |
| 要碰 NX 那一层 | [`docs/NX_ADAPTER.md`](docs/NX_ADAPTER.md) |
| 想知道自己准不准、怎么标 | [`docs/LABELING.md`](docs/LABELING.md) |
| 想找模型试手 / 看边界场景 | [`docs/DEMO_SCENE.md`](docs/DEMO_SCENE.md) |
| 想算性能预算 | [`docs/PERF.md`](docs/PERF.md) |
| 要启动 Web 平台 / 看接口 | [`nxdrp/checkers/platform_web/README.md`](nxdrp/checkers/platform_web/README.md) |
| 要出报告 / 对接 报告 | [`nxdrp/checkers/report/README.md`](nxdrp/checkers/report/README.md) |

前两份先读，中间两份是工具书——**写 checker 时不用通读**，用到哪节查哪节。
后三份是「验证」环节的手册：写完不跑一遍，等于没写。
