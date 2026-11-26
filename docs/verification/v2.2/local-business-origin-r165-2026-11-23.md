# R165 独立业务来源的固定绑定

2026-11-23，独立工作区 `output/v22-dev-isolated`、`codex/2.2`。依据 V2.01 后端 6.3、6.5、7.5 和前端 6.1。

- `backend/tests/infrastructure/test_v22_business_origin.py` 等六组专项共 117 项通过。实际写入并按摘要读取访问策略，核对标准 HTTPS 和隔离验证端口、原本地地址、Caddy 生成片段、登记资源和恢复观察。外域配置、篡改、路径、通配及其它非规范地址拒绝。
- `node --test tests/environment-binding.test.mjs` 17 项通过，前端 `npm run typecheck` 和 `npm run format:check` 通过。真实客户端构造匹配时进入握手；浏览器来源、环境标签或地址格式不匹配时只尝试引导文件。测试不连接外部域名。
- Windows 适配了 Linux 根与受保护文件读取边界。Caddy 的实际受控进程、云 DNS、证书及公网发布本轮未执行。
