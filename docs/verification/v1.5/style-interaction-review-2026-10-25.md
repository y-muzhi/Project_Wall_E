# V1.5 样式与交互自查

2026-10-25（Asia/Hong_Kong）。用户授权自行检查并修复。使用Playwright技能及本机离线CLI／Chrome独立headless，tools/serve-v15-offline.py提供临时生产前端、真实FastAPI／SQLite／Worker，私有Counter／Gateway；未访问真实模型或计数API，未编辑用户库。原8000／5173服务保持运行，当前前端修改通过原Vite机制提供。

实际修复：操作设置文字／展开箭头／键盘焦点与Esc取消配置；迟到绑定GET失效、保留消息文本、不改已发请求；目标摘要显示实际文档名和Vn；文档创建字段与错误定位；目录选中状态、长名称与维护操作分区、改名焦点及中文输入保护；参考文档／固定结构复选框对齐；进展依据状态和未决主题名称中文展示。代码与规则见archive/iterations/v1.5/WALL-E.样式与交互自查修复_V_1.5.md。

## 离线检查

- frontend目录`node --test tests/v15-ai-composer.test.mjs tests/v15-directory.test.mjs tests/detail-layout.test.mjs`：22 passed／285.82ms，含三项新增配置取消、迟到GET和发送保护；没有为可逆样式逐条制造测试。
- 最终完整`npm.cmd test`：358 passed／1733.69ms，无失败或跳过。
- 最终`npm.cmd run typecheck`：退出0。
- 最终`node node_modules/vite/bin/vite.js build --outDir <本轮临时目录>/frontend --emptyOutDir --logLevel warn`：退出0；仅既有大于500kB的chunk提醒。此前本轮可读构建1253模块／507ms，后续补文案后再次成功，不把前次时长冒充最终。未覆盖项目frontend/dist。

## 实际浏览器检查

通过UI创建隔离需求和一份21字长名称空白文档；用户服务与库未写。修复前确认设置摘要没有明显设置文字／focus样式，Esc后仍open；修复后选择另一操作再Esc，实际恢复“讨论／未指定文档”，消息“保留未发送的输入”保留、焦点回操作设置，focus-visible为true且outline=solid。

改名实际聚焦INPUT并选中21字原名，Esc后无改名表单，焦点回“改名”。新建文档空名点击创建，输入aria-invalid=true、错误说明关联并聚焦名称，footer底部600等于短窗口高度600。弹窗下拉第一次Esc仅关闭菜单，第二次关闭弹窗并返“新建文档”。

1280×600实际无整页横向／纵向溢出，发送按钮底部558；展开设置后正文区域可滚动、发送footer保持558。1024／1100／1440／1920×800下scrollWidth分别等于视口宽度，scrollHeight均800，发送按钮底部分别766／766／758／758，跨尺寸未发送文字保留。1100抽屉导航Esc后收起并返回展开入口。对长名称、目录选中及设置按钮作少量视觉检查，未逐项截图。

隔离讨论实际发送一次，Counter／Gateway各1次（真实供应方0）；实际展示运行、建议卡片及请求详情。进度依据从“用户陈述 · ACTIVE”修复为“用户陈述 · 当前有效”；未决主题显示“目标”而非内部ref。请求详情Esc关闭后下一帧焦点回“查看上下文”，没有新增模型调用。最终页面console Errors=0、Warnings=0。

## 清理及范围

只关闭本轮浏览器walle-ui-20261025；向PTY17179发送stop，隔离服务PID57116／端口51605正常退出，输出OFFLINE_COUNTS count_batches=1 chat=1及OWNED_TEMPORARY_SERVER_STOPPED_AND_OUTPUT_CLEANED。TemporaryDirectory负责清理SQLite、CLI快照／少量截图、配置和临时构建；最终存在性／项目清理及用户端口检查见收口现场。

本次不作为真实模型效果或完整语义验收，不覆盖全部操作系统中文输入法、所有菜单／多标签断网组合；中文组合保护有实际事件分支与类型检查，未声称真实IME人工逐项通过。后端、冻结模型资源与真实旧证据不改，未执行Git写操作。

收口现场：临时目录存在性False、51605无监听，原8000／29692及5173／57236继续监听；`cleanup-test-artifacts.py --dry-run`显示JSON=0／screenshots=0，`git diff --check`退出0（仅CRLF规范化提示）。GET5173当前composer模块及CSS均200并含新设置／元数据样式。正式FE当前SHA256=`63a2b56b48c155d80fce512b5750a4fe377421b12bbca5b62b84d4b5d5fe8305`，采用时旧摘要保留。
