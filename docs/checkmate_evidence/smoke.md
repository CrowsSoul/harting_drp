# Check-Mate 许可与环境冒烟（W1）

日期：2026-10-30；机器：Windows 10 Pro，NX `Designcenter2606`（`C:\Program Files\Siemens`）。

## 结论

**Check-Mate 可运行，黑盒差分通道成立。** 产品自带的 DFM Advisor 检查器（`dfms_*`）
可直接经 `CheckerExecutor` 执行，并生成 PLMXML 判定日志；检查参数可按名覆盖。

## 实测记录

| 项 | 结果 |
|---|---|
| `NXBIN\run_journal.exe` 驱动 | 可用（项目现有 `run_journal` 通道直接复用） |
| 检查器 `dfms_DeepHoles` | 可执行，日志 `DeepHole.xml` 生成，`status=fail`（默认参数） |
| 参数覆盖 `ld_ratio_max=30.0` | 生效，同一零件判定变 `pass` |
| 参数覆盖 `ld_ratio_max=2.0` | 生效，两条孔均判 `fail` |
| Check-Mate 自带 Python 示例检查器 `Examples_NXOpenPython_CheckDeepHoles` | **未注册**（需按官方 readme 放到用户目录 `application\` 下）；不影响黑盒差分 |

观测到的判定细节（`dfms_DeepHoles` + 示例零件 `DeepHole.prt`）：

- 两条孔 `L=95.0/D=3.5`、`L=90.0/D=10.0`；
- 报错文案给出 `L/D` 值与判据 `5.0 < L/D`；
- 说明 Check-Mate 用的是**严格大于**比较，与我们"恰在阈值不报"的语义一致。

## 使用注意

1. `SetParameter` 类型敏感：float 参数必须传 float（`2` 不行、`2.0` 可以）；
2. 结果以 XML 日志为准（`Validator` 对象在 Commit 后不保留检查节点）；
3. 日志目录须可写（不要落在 `Program Files`）；
4. 产品示例检查器若要用，需复制/注册到用户目录——**我们不复用其源码**，只取其判定口径。

## 复现

```bash
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles
python tools/checkmate/run_checkmate.py smoke --checker dfms_DeepHoles --param ld_ratio_max=30.0 \
  --out .local/checkmate_results/dfm27-deephole-pass30.json
```
