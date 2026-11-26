# R335 两套真实 WALL-E 的 Chromium 隔离验收

2026-11-24（香港时间）。独立 `codex/2.2`，Ubuntu 24.04.5 x86_64、无网卡来宾。实际普通程序 `2ccc33c19afd0f23423dc9423d3cd08414a79efc9297b380664c7568275a16eb`，SQLite 3.54.1，Schema `2639f06f41b13892bc2c78a9228d278665e11f74e10e88f2b388b1dee87aafdf`，两份实际业务安装与独立 Unix 套接字。Caddy HTTPS 仅来宾 9443，两个公开入口各有准确域名及自己安装生成的 Web 身份。

- 两个新建非 root 浏览器用户、独立 Chromium 持久资料和服务身份。Chrome for Testing 158.0.8127.88、Playwright CLI 0.1.24、Node.js 24.15.0，1360×900。每一份浏览器配置仅允许自己的准确 HTTPS 源。实际 Caddy TLS 先通过来宾专属 CA 校验，浏览器会话临时接收该测试证书。宿主浏览器和服务保持原运行环境。
- 两个页面各自通过实际“新建需求”创建需求。需求列表只显示该环境的原测试数据。进入原需求，在“更多操作”选择“人工编辑”，输入该环境独有的标记、等待自动保存、点击“完成编辑”。两边均从实际业务 API 读到对应正文，并在浏览器刷新后读回。实际历史状态保存该环境源、环境 ID 和数据代次。人工编辑时均打开真实 IndexedDB，观察的浏览器状态不包含另一环境绑定。
- 开发站正常关闭时，集成站同一浏览器继续读回自己正文。集成站正常关机并实际重新启动，运行 ID 已更换，数据代次保持；同一浏览器刷新和 API 均读回原保存内容。两站关闭、两个浏览器会话与 Caddy 退出。

执行 `python run-guest.py r335g-ui disk-r335c-node.qcow2 offline 500`，来宾退出 0。早期夹具修正了 WEB 身份、Node 版本、无网卡测试名解析、实际“需求新增”文案和 frame 引用。真实应用代码、绑定规则及数据隔离门槛未因夹具修正变化。这里验证本机普通双站，固定正式候选、ARM64 和生产另验。[Chrome for Testing 官方发布](https://googlechromelabs.github.io/chrome-for-testing/) · [Playwright CLI](https://github.com/microsoft/playwright-cli)
