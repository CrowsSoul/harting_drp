# 桌面发布目录

运行本目录 `HartingDRP_NX.exe`；这是本地唯一桌面程序，整理前的 EXE 字节及 SHA256 保持不变。完整说明见 [项目 README](../README.md)，演示见 [演示脚本](../docs/DEMO.md)。

需要 Windows x64 和 WebView2 Runtime。无 NX 可打开平台使用 JSON 示例；实际建模、改参、插件及原生求解需要 NX／完整 Siemens 求解器及相应许可证。软件和许可证不随包分发。

`samples` 是既有 PRT 演示模型。`simcenter-project.example.json` 只是完整工程接口的描述格式，不是可直接求解工程。

原生电热演示默认 20 A 应得最高温度约 26.34688°C，40 A 约 30.38750°C。范围为一维均匀导体、常物性、两端恒温；完整 SIM/FEM 工程仍需具体工程验收。

本目录由 Git 忽略；后续可压缩整个 release 文件夹作为 GitHub Release 附件。单独分发时，配套说明与样例需一起保留；不要加入个人账户目录。校验见本目录 SHA256.txt。
