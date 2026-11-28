# R159–R161 受管程序回退页面与登记

2026-11-23，独立工作区 `output/v22-dev-isolated` 的 `codex/2.2` 未提交代码。采用 V2.01 后端 4.10、4.11、4.12.3、6.6、7.10 和前端 5.9、6.4。

- `npm run typecheck` 与 `npm run format:check` 通过。真实 Firefox 访问隔离管理页面，验证开发者无程序回退入口、管理者在未核验条件下可见禁用原因、就绪后可以生成计划并二次确认。实际管理 API 使用独立 SQLite，收到 HTTP 202 和 `ACCEPTED`。检查宽 435 与 1180 CSS 像素的确认区域。临时 HTTPS 回环使用本轮端口 58900，测试脚本负责停止服务和删除浏览器配置、证书及数据。
- `python -m pytest -q backend/tests/infrastructure/test_v22_managed_program_release.py -o faulthandler_timeout=15` 的普通发布和回退场景共 2 项通过。运行时为项目锁定 Python，Windows 本地 POSIX 接口仅用于测试适配。用真实管理事务和新代次 SQLite 核对回退开放采用、原操作回放、容量保留、同源业务入口随新部署更新，以及移除目录授权后关闭入口。仍需在实际 Linux 进程和网关验证。
- 源码快照为本轮工作区，真实供应方调用、正式服务更新和生产数据采用未执行。物理控制文件选择的断回执专项在下一单元单独记录。
