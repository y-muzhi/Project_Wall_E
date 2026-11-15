# V2.0 OpenCode 固定二进制准入

2026-11-08，依据 BE 7.4.1／7.4.4 和 START.CHECK_CONDITIONS。正式设计保持原样。

- 只接受已经确定的 OpenCode 1.19.5 Windows x64 官方 ZIP 及其固定 SHA256。先校验原 ZIP 字节，再对唯一根目录 opencode.exe 有界读取、校验 PE 架构并计算原成员摘要。通过本机文件身份及锁定句柄，将该成员与受信安装提供的实际程序对应。浏览器不提供路径、摘要或版本覆盖。
- CHECK_CONDITIONS 私有安装可以提供原包及原程序，需与任务固定版本、程序引用及运行包引用一致。检查记录单独保存二进制来源事实。真实执行环境仍需完整配置／依赖、LPAC／WFP、受控原生身份和模型准入。验证不启动程序、不安装或改变系统。 [官方固定发布资产](https://github.com/anomalyco/opencode/releases/expanded_assets/v1.19.5)

- 固定 OpenAPI 原文按设计字节数和 Git blob 验证，再核对 17 项采用的方法与成功码。原文检查单列，实际实例版本与响应仍由运行证据确认。

## 运行包原字节预检

BE 7.3／7.4.4 已要求以不可变清单固定 runtime_bundle_ref。本批采用 `opencode-bundle:sha256:<清单原字节摘要>`，清单使用 schema_version=1、configuration_policy=OC20-CONFIG-1 及 members。每个成员记录原相对路径、字节数和 SHA256。受信安装提供清单位置及独立运行包根，浏览器不提供路径或摘要。固定包的配置、.gitignore、package.json、package-lock.json 与 node_modules 必须存在。校验根目录完整清单、实际原字节及禁止扩展的配置字段。发现额外文件、摘要不符或依赖声明与锁文件根记录不一致时拒绝。固定源码会尝试准备 @opencode-ai/plugin，本批核对 1.19.5 的根依赖、锁内版本和安装成员；锁内非可选依赖缺少已列入清单的 package.json 时拒绝。预检不创建或修复文件，不尝试补依赖。字节预检与任务 LPAC 只读证明、供应方隔离和实际配置生效分开记录。 [固定提交的依赖装载逻辑](https://raw.githubusercontent.com/anomalyco/opencode/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/npm.ts)
