# WALL-E V2.2 普通入口与前端环境归属验证

2026-11-20（Asia/Hong_Kong）。Ubuntu 24.04 ARM64／ext4 专用验证机，开发 worktree 为 `~/walle-v22-validation/scopes/development/source`、分支 `codex/v2.2-development`，HEAD `a0f40592702cb702ed928849ac540479c22c224f` 加本轮实施。固定运行包沿用 ARM64 r3。C1 Schema 摘要为 `5662047ae0e0ec41dea7b55d441c7834abeb07a3535b5ddc4f4a0830aa965b65`，对象契约与 A2/B3 一致。

| 验证项 | 实际操作及结果 |
| --- | --- |
| C1 Unix 连接组 | 两套独立安装 `/opt/walle-v22-validation/environments-c1-r3/{95ab00f8-2869-4039-906f-dcfc90e1e197,b6d28711-40d0-47de-9630-eb2cfb29ce63}`，均通过真实普通服务维护入口初始化并用不同身份运行。专用代理身份 UID 42551 持两个连接组 42531、42541，可通过两处 Unix 套接字核对已绑定健康接口。业务库、控制、锁和维护文件的越权文件访问均被系统拒绝。两套服务按原稳定锁 PID 停止，返回 CLOSED。 |
| C1 HTTPS 配置生成 | `environment_gateway.py` 读取两套真实安装绑定，使用显式的合成凭据测试描述，生成两套站点和 `.well-known` 描述。核对站点来源、认证标签、Unix 地址、绑定摘要、受信转发及独立静态根。计划验证端口 9443，未监听。 |
| C1 前端传输 | `node --test tests/environment-binding.test.mjs tests/api-client.test.mjs` 在本机和 Linux 验证机通过 19 项。覆盖严格配置与握手顺序、重复键、错误响应作用域、冻结请求与原结果、持久键与历史信封。Linux 格式、类型及独立构建通过，产物 `web-c1-binding` 120 个文件。 |
| C2 人工草稿 | 在实际用户编辑会话的仓储构造器传入已经绑定的环境作用域。C2 在部署分支以生产仓储和替身事务检查不同代次的数据库名、版本和键。另执行业务目录、人工草稿恢复和编辑完成回归。五组，共 40 项通过。独立构建 `web-c2-draft` 共 120 个文件，格式与类型检查通过。 |

C2 离线命令为 `node --test --test-timeout=10000 tests/environment-binding.test.mjs tests/api-client.test.mjs tests/v15-directory.test.mjs tests/manual-recovery.test.mjs tests/manual-end.test.mjs`、`npm run format:check`、`npm run typecheck`、`npm run build -- --outDir "$scope/web-c2-draft"`。初次运行的测试替身用 Set 模拟 DOMStringList，缺失 contains 方法，导致验证停在打开阶段。终止该次验证，修正替身并增加检测超时后复验通过。Vite 构建仍报告既有主包大小提示。

自动审批服务两次以 HTTP 403 中止固定 Ubuntu Caddy 2.6.2 ARM64 包下载，下载命令均未执行。实际 Caddy 配置加载、TLS、域名和客户端信任、外部认证边界及端到端浏览器验收待验证。原生 IndexedDB 和正式页面启动的接续见 [C5—C7](environment-command-entry-c5-c7-2026-11-20.md)。容量矩阵、跨标签和真实 HTTPS 浏览器主链路仍待验证。未发起模型、计数或其他付费调用。验证过程不留原始请求或输出日志。
