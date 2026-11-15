# V2.0 OpenCode 运行包预检

2026-11-08（Asia/Hong_Kong）。Windows／NTFS，隔离 SQLite 3.54.1，db20-r29。按 BE 7.3／7.4.4 与[独立迭代](../../iterations/pending/v2.0/WALL-E.OpenCode固定二进制准入_V_2.0.md)实施。

- 受信安装提供清单及运行包根。当前以清单原 SHA256 固定 runtime_bundle_ref。实际路径、完整成员、每项原字节、独立配置开关、根依赖声明、固定插件版本、npm 锁及存在的包文件均通过校验才报告预检成功。非可选依赖缺文件即拒绝。Windows 原文件租约仅用于本次预检。 [OpenCode 固定 npm 源码](https://raw.githubusercontent.com/anomalyco/opencode/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/core/src/npm.ts)
- 原 START 保存独立的 executor_runtime_bundle_verified。旧回执没有该字段时可读。缺运行包归入 Q20-CONFIG；即使固定包来源、协议源和运行包三项通过，缺实际隔离能力时仍保持 CONFIG_NOT_READY。API17 仅返回布尔和安全原因，不公开安装路径或配置内容。
- 定向 pytest 38 项通过，185.52 秒。覆盖原 OpenCode 来源／运行包／系统配置、NTFS 变更和额外成员、npm 依赖缺失、别名、原 START 工作区／依据、原操作投影、缺失或夹具来源齐备时拒绝进入 START_INSTANCE。tools/check-opencode-binary.py 本地 CLI 以临时六成员包实际执行并通过。Ruff 检查及 274 文件格式通过，git diff --check 退出 0，既有前端文件有 CRLF 提示。
- 运行包接入后的真实 Guard／MinGit 原 START 组合（test_fixed_baseline_http_reads_and_creates_one_task_in_private_guard_scopes[start]）1 项通过，209.51 秒。缺正式执行器准备时，固定仓库路径和原操作仍可核对，实际 START 保留原 202 并在启动实例前阻断。测试没有运行 OpenCode。
- 需独立完成实际 OpenCode ZIP／完整部署包、LPAC 只读和网络规则、实际启动／响应及配置生效。当前未安装软件、未改系统 ACL／WFP、未启动 OpenCode、未更新用户服务、未触发真实模型。
