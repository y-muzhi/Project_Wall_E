# 前端实施边界

已按D-003安装精确依赖，完整传递依赖锁定在package-lock.json。当前实际代码为投影文本选区辅助函数，页面、路由、Milkdown实例/原始节点适配及HTTP尚未创建，不能作为可运行应用或编辑器验收。

在项目根运行：

```powershell
node tools/verify-frontend.mjs
```

在本目录重新安装/检查：

```powershell
npm ci --no-audit --no-fund
npm run typecheck
npm test
```

selection.ts接受一个Block按共同方言投影的纯文本内的UTF-16偏移，输出D-004规定的码点半开选区；不直接接受DOM节点位置。真实编辑器必须先证明DOM/ProseMirror到这一投影的映射与单Block约束，父页面按document_id/content_version拒绝迟到事件。共享selection-v1.json同时由后端真实Markdown解析/锚点定位与前端转换测试核对。

当前测试不证明浏览器焦点、布局、滚动、IME、Markdown往返或自动保存，相关设计场景仍未执行。尚未提供业务页面启动命令。
