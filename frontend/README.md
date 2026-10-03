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

identity.ts安装顶层节点walle_block_id属性（不进Markdown）、初始显式绑定、StepMap原节点继承、新插入/复制新ID、拆前保留/合首保留、显式整体移动、同编辑器真实history恢复及高水位。未知粘贴不信任携带ID，内部节点清除顶层身份；空文档caret不分配业务ID，容量失败不改原状态。空段落边界合并优先执行真实join，避免通用删除把首个ID丢弃。属性修正只setNodeMarkup，保留光标与history；位置二分查找，未变节点复用。当前13项身份测试，加7项选区共20项；浏览器额外核对全部15例身份属性/DOM与10步真实键盘。它仍不是完整编辑器：尚缺编辑后的源码重组/完整BlockState输出、来源/草稿应用绑定、选区DOM映射及生命周期。

空白边界：新空段落只作gap，不预占ID；输入正文后分配。已有拆分前段身份保留；含gap的显式移动跳过空gap的来源声明。验证Vite禁用HMR，源码/探针/夹具/lock/验证工具前后哈希一致才判通过。早期热更新中断的失败证据保留。
