# R351 发布切换的浏览器配置重新核对

2026-11-24（香港时间），独立 `codex/2.2`。依据 V2.01 后端 4.11、前端 4.3、4.4、4.7。前端只在同一环境与数据代次的公开配置和应用摘要匹配后更新当前观察。原环境或数据代次错配继续冻结原页。

- `node --test --test-name-pattern 'partial configuration switch' tests/environment-binding.test.mjs` 对旧实现复现 `SCOPE_CHANGED`，再次核对被禁止。修复后 `node --test tests/environment-binding.test.mjs` 18 项通过，含实际错代次阻断、原作用域不变、重查期间拦截新写操作、恢复后由用户指示才发送。
- `npm run format:check`、`npm run build -- --outDir ../output/.v22-local-r346/frontend-dist` 通过，包含 TypeScript 及 120 个普通发布文件。Vite 提示已有较大入口包。全前端使用项目支持的 `WALLE_OFFLINE_TEST_PYTHON` 绑定本机离线后端解释器后，606 项全部通过。无此变量时独立副本没有默认 Windows venv，跨语言字符归一检查曾失败。
- 实际 Chromium 在无网卡 Linux 的两个真实 WALL-E 环境上完成配置摘要错配／恢复。页面在原作用域保留输入，核对后无自动写，显式保存、完成编辑、刷新和真实 API 读回通过，另站正文不变。仅公开配置的错配输入由浏览器路由模拟。初次原生介质补齐固定资源，CLI 按声明的精确 Core 版本重跑。`r351b-browser` 退出 0。[R357 扩展](local-x86-draft-resume-version-r357-2026-11-24.md)
- 此项修复继续等待实际集成交付和正式候选。
