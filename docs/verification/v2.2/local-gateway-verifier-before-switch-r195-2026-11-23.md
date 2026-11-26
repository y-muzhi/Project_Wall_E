# R195 固定切换前核对只读复验角色

2026-11-23，在 Windows 独立 `codex/2.2` 使用锁定 Python、SQLite 3.54.1。依据 V2.01 后端 4.11、4.12.2 和 [独立入口接续](../../iterations/pending/v2.2/WALL-E.普通环境受信HTTPS入口接续_V_2.2.md)。

- `prepare_target` 在安装独立 HTTPS 目标时核对即将采用的固定访问策略。真正创建原选择记录以前的 `select_release_deployment` 再校验。验角色和受保护策略与实际 HTTPS 进程、凭据复验分开。
- 只有 WEB 只读或可写 AUTOMATION 时，真实目标准备返回 `RELEASE_GATEWAY_VERIFIER_REQUIRED`。通过原重配流程加入只读 AUTOMATION 后，仍可准备原站点，源策略未动。更改角色缺失的旧待选目标在记录和指针写入前拒绝，原控制和 SQLite 不变。受信准入后模拟回复丢失，按原键读回同一转换及控制摘要。
- 使用 `python -m pytest` 在固定 SQLite 下运行相关业务来源、受管发布、重配、登记恢复、备份和结构等 12 组专项，176 项与 16 个子项通过。第一次发现重配夹具未提供原作用域字段，补齐后复验通过。Ruff F／I、664 个 Python 文件格式与 `git diff --check` 通过。保留 Starlette 测试客户端的已有弃用提示。
- 实际生产变更、ARM64 最新候选和受管固定候选的本机完整切换本单元未执行。
