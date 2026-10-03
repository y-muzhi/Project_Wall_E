# 前端实施边界

已按D-003安装精确依赖，完整传递依赖锁定在package-lock.json。当前包含选区辅助函数与真实Crepe原始节点/初始源码适配层；业务页面、路由及HTTP尚未创建。

在项目根运行：

```powershell
node tools/verify-frontend.mjs
node tools/verify-editor-browser.mjs
```

在本目录重新安装/检查：

```powershell
npm ci --no-audit --no-fund
npm run typecheck
npm test
```

selection.ts接受一个Block按共同方言投影的纯文本内的UTF-16偏移，输出D-004规定的码点半开选区；不直接接受DOM节点位置。真实编辑器必须先证明DOM/ProseMirror到这一投影的映射与单Block约束，父页面按document_id/content_version拒绝迟到事件。共享selection-v1.json同时由后端真实Markdown解析/锚点定位与前端转换测试核对。

source-nodes.ts在create前安装，保留重复引用定义及惰性HTML文本节点、行内图片alt、代码尾换行；关闭会删除定义/改变HTML类型的默认插件、自动尾段和临时blob上传。editor-source.ts将原文片段、空白gap、初始节点、投影和章节路径同时绑定。unchangedMarkdown仅在真实节点未变化时返回原文，编辑后拒绝返回旧源码；不能用Crepe.getMarkdown替代源码保存。尚未实现编辑后身份与源码重组、完整BlockState及应用接入。

浏览器验证脚本使用Playwright CLI技能包装器（Windows需Git Bash及npx；可用WALLE_BASH/WALLE_PLAYWRIGHT_WRAPPER指定路径），在独立5174端口启动测试探针，使用自己的浏览器会话并在结束后关闭。15个独立共享样例覆盖11类型、CRLF、重复定义、图片、代码尾行、空文档、未闭合/未注册语法；断言真实节点投影、原文保留、编辑拒绝旧源和HTML不执行。原始输出存docs/verification，截图存output/playwright。手工探针可在本目录运行`node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173`后访问`/tests/browser/editor.html`，它是测试工具。

这些验证不证明产品布局、焦点、滚动、IME、自动保存、完整方言边界或编辑后往返，373项设计场景仍未执行。尚未提供业务页面启动命令。
