# 对话发送快捷键检查

2026-10-27，M15-INPUT-01，代码基线422cc98e7595cad5f22ab78c9f83068199a05392。用户明确Enter发送、Ctrl+Enter换行。仅改主对话输入分类／事件及提示，复用原owner草稿与send／canSend门禁；卡片、评论、正文及后端权限不变。不写用户库、不调用真实模型／计数、不做Git操作或启停用户服务。

## 实现与设计

已读AGENTS、正式FE SHR-UI键盘／对话输入表及实际composer-view、send-shortcut、相关测试和owner发送校验；未重审全部模型资源。composerShortcut区分SEND／NEWLINE／IGNORE，Enter阻止默认换行并调用原send，Ctrl／⌘+Enter使用textarea.setRangeText在光标处插入换行／替换选区，原owner.change保存草稿。组合状态、native.isComposing及keyCode229不拦截，重复回车不提交；Shift+Enter原生换行保持。按钮提示为“Enter 发送 · Ctrl / ⌘ + Enter 换行”。

修改3文件：frontend/src/guide/send-shortcut.ts、composer-view.tsx、frontend/tests/send-shortcut.test.mjs；路径UTF8＋NUL＋原字节＋NUL排序聚合c67939a41da324963e4c06ed3ac65b888e222c911392297871762560c23e54d7。正式FE仍1.0／EFFECTIVE，SHA256=3e8f5c48fe2f77f3e85d25d2955340d0741b50ff8e71bb32b6114032e5125277；BE保持fc34481af473ea40617cd859329f07aa03147c19d983f3f700c1b6a9ea02359d，资源／HTTP不变。

## 离线与构建

快捷键2项通过／85.7144ms：普通Enter、Ctrl／Meta换行分类、Shift／Alt／其他键、defaultPrevented、组合／229、repeat及不可发送门禁。npm.cmd run typecheck退出0；最终npm.cmd test为406 passed／6864.1584ms。没有新增后端专项，发送契约未改。

tools/serve-v15-offline.py --serve在独占TemporaryDirectory内完成Vite生产构建，退出0后启动真实应用；frontend/dist未覆盖。仅原工具Starlette弃用提醒。截图非本轮必要输出，未生成保留截图。

## 隔离真实页面

Playwright技能CLI，独占PID50560／PTY14027／57587，根walle-v15-browser-8b17yjkb，命名浏览器walle-input-enter。原HTTP新建独立需求，私有Counter／Gateway，真实供应方0。

1. 主输入“甲乙丙”光标1按Control+Enter，实际变“甲\n乙丙”、光标2；原input事件由owner保持。
2. “abcd”选择1—3按Control+Enter，变“a\nd”；再Meta+Enter变“a\n\nd”，这三次无guide-runs提交。
3. 合成isComposing=true的Enter事件defaultPrevented=false，未发送。此项是合成事件／离线守卫证据，不冒充Windows系统输入法端到端选词或原生macOS验收。
4. 输入“第一行\n第二行”后实际Enter，只有1次POST guide-runs，返回202；真实请求instruction和最终保存的USER消息精确保留同一换行。隔离GuideRun1最终COMPLETED，LLMUse1。
5. 空输入Enter仍为空，0额外提交；Shift+Enter原生得到单个换行。console0／错误0／警告0。

初期CLI open返回进行中，紧随的一次find提示浏览器未就绪；等待原open进程完成后继续，没有重复启动或业务提交。未掩盖产品失败。

## 清理与边界

浏览器close，PTY14027 stop退出0；Counter1批／Gateway1次均私有，真实API0，自动清理完整。独占数据库、快照和配置不保留，无JSON／日志／截图或录像。原用户8000／47020／PTY84129、5173／12440保持，本轮无需重启；前端Vite提供新源码，入口http://127.0.0.1:5173/requirements，8000静态dist未重新部署。

未覆盖：真实OS中文／日文等输入法、原生macOS／Safari及其他浏览器／缩放组合；IME已有双守卫及React状态保护。未在用户当前对话代发Enter、修改正文、取消任务或触发真实调用。Git未提交／推送，本次不复用此前已完成的推送许可。

最终用户现场只读复核：8000／47020、5173／12440仍监听，需求页、composer-view及send-shortcut模块3项GET200，新提示／setRangeText及分类已由Vite提供。15份变动Markdown共398本地文件链接有效，git diff --check退出0；独占根不存在，清理dry-run为JSON0／截图0。HEAD仍422cc98，当前修改未提交推送。
