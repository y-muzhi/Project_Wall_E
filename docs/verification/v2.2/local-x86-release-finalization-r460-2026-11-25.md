# V2.2 R460 固定候选的四类实证、最终组装和封存

2026-11-25（香港时间）。验证既有集成提交 `deacba8a9545122f35a2f85c125a354205e06461`，源 tree `5230b7123a763b944f2cd45cb270f6c0b531b828`。固定 Ubuntu 24.04 x86_64、ext4、运行包 `0241128f2faa82bcc1f34d3f87196b0b817333caec2d070bf5a91f0cd3998e9e`。WHPX 来宾 PID 52032，无网卡及转发，实际网关仅来宾回环 9443。

- 同一来宾使用实际 Git 及原管理 SQLite 登记开发与集成交付。中转固定程序、Schema 与前端。实际候选创建并保存需求文档、错作用域拒绝、正常停止和重启读回，真实 Caddy HTTPS 和独立沙箱浏览器实际编辑、保存、刷新及 API 读回。由另一物理根、应用／维护 UID 和数据代次的普通集成站获取本地可移动备份，再在独立只读恢复安装中核对真实正文及历史，得到产品 `LOCAL_VERIFIED` 回执 `639f268b10ae602cab566170efee4a7a33340c3adb7d499e15d6b3198a97ae16`。
- 四类证据均引用同一候选工件。实际前端独立离线构建与新中转前端索引的对应关系见 [R461](windows-fixed-frontend-twin-build-r461-2026-11-25.md)。先去掉 `BROWSER_FLOW`，`prepare-release-final-build` 明确返回 `RELEASE_FINALIZATION_EVIDENCE_REQUIRED`，最终组装根和发布根保持空目录。恢复完整四类引用后实际组装，同计划重取一致。
- 原 `seal-release` 实际封存且重放一致，封存清单 SHA256 `3187b185512b2bae091cd95e6aedfb4701e9466059f934c0b92e95014d72d455`。原 `candidate --require-release-evidence` 返回 `REQUIRED_EVIDENCE_RECORDED`，清单摘要一致，原中转包复验一致。该包为本机隔离试验产物。
- 早期同一验证脚本误用了浏览器状态表旧标签，之后出现两个测试身份目录名重复，两处均修正并在新覆盖盘完成整套联验。两阶段的产品准入和权限保持。最后对比 133 项当前源码摘要，Linux V2.2 后端专项 298 项通过、2 项平台跳过，6.99 秒及一条既有 Starlette 提示。应用、私有恢复、Caddy、浏览器和本次来宾退出，`WALLE_QA_DONE:0`。

最新工作树形成受信正式交付后，要按该提交的确切源码、目标平台和固定工件重新取证。ARM64、实际双宿主 COS、正式维护采用和生产接入分别验收。
