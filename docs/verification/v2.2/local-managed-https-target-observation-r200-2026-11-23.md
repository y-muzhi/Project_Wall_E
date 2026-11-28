# R200 管理目录的 HTTPS 目标观测门槛

2026-11-23，Windows 独立 `codex/2.2`。以 V2.01 后端 4.11、6.5 和 [入口接续 R195](../../iterations/pending/v2.2/WALL-E.普通环境受信HTTPS入口接续_V_2.2.md) 为依据，沿实际 `manage_registry.py observe-release-source` 路径复核目标安装。

- 固定访问策略缺独立只读自动化身份时，原生主机入口返回 `RELEASE_GATEWAY_VERIFIER_REQUIRED` 并不生成目标观测。新选择与既有原转换各按 R195 检查。已写的观测仍按原计划及有效期核对，新进入维护的实际状态另行实测。
- 真实隔离管理 HTTP 和 SQLite 测试覆盖发布、程序回退、重配三种目标。每种均不形成新就绪凭证，源库字节保持，管理目录请求成功并说明 `SOURCE_UNVERIFIED`。同一专项含既有合规路径的受理、切换和原键续查。
- 使用固定 SQLite 3.54.1 执行关联 12 组测试，182 项与 16 个子项通过。Ruff F／I 与 `git diff --check` 通过。保留 Starlette 测试客户端既有弃用提醒。
- ARM64 最新源码、生产接入、实际 COS、真实受管发布的原生完整切换均另行核验。
