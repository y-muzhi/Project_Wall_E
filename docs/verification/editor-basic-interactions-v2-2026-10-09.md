# UX-018 编辑器基础交互检查

日期：2026-10-09。范围：斜杠菜单、选区格式、正文快捷键及原编辑保护。采用规则见[迭代优化V2第26节](../design/WALL-E.V1_0.6.迭代优化V2文档.md#v2-18-implementation)。不代表完整业务验收。

## 构建与基础测试

在frontend执行：

```text
npm.cmd run typecheck
npm.cmd run build -- --logLevel warn
node --test --test-reporter=spec tests/editor-interactions.test.mjs tests/navigation.test.mjs tests/detail-interaction-feedback.test.mjs tests/presentation-basics.test.mjs
```

类型检查与最终生产构建通过；仅有既有超过500kB产物提示。16项基础检查通过，失败0，其中新增4项使用真实ProseMirror状态验证触发边界、原子事务、查询失效及链接文字保留。新命令未增加依赖或修改后端契约。

## 隔离浏览器短观察

使用tests/browser/editor-interactions.html内存夹具，真实RequirementEditor及账本；没有业务API、数据库、自动保存或模型调用。通过用户可见的夹具选择按钮和真实编辑区键盘操作验证，浏览器没有通过脚本直接修改正文。

|范围|实际结果|
|---|---|
|斜杠菜单|替换“插入位置”为“/”后就地出现插入类型；点击表格得到3×3表格，有效状态true，Markdown表格生成。Ctrl+Z返回“/”，Ctrl+Shift+Z重建表格|
|搜索与键盘|输入/list，显示无序／有序两项；↓＋Enter插入有序列表，后续输入“列表内容”正常。/bullet＋Enter插入无序列表；/h2＋Enter＋正文输入形成标题2|
|选区浮动格式|选中“正文测试”出现浮动栏，点击选区加粗后Markdown含**正文测试**；浮动样式选择标题2后实际h2文字保持原内容|
|快捷键|Ctrl+B生成真实strong；Ctrl+I生成em，Ctrl+Z撤销斜体；Ctrl+Z后Ctrl+Y重做加粗。Ctrl+Shift+8将选中文字转无序列表。Ctrl+K在选区附近打开链接表单|
|链接|选中文字提交https://example.com，链接地址正确、原文字仍为“正文测试”；/link插入地址作为可见文字。javascript:alert(1)在表单被拒绝并显示说明，没有执行该地址|
|Esc和Backspace|编辑区Esc关闭选区浮动栏；/菜单Esc关闭后正文仍保留“/”，Backspace可删除它，再输入/h2可重新触发。菜单没有在未改变查询时立即重开|
|只读和模板锁|冻结内存编辑器后aria-readonly=true，选区浮层隐藏。初始化文档选中“背景与目标”尝试改为标题3，原h2保留；账本仍有效，实际提示要求保留模板标题|
|尺寸|1280×900及1024×768观察就地浮层；1024px下浮动栏边界x112至480.5、y134.5至180.5，处于窗口内，整页scrollWidth为1024|
|销毁|多次重置内存夹具、销毁／重建编辑器，控件正常重新出现。针对销毁顺序，浮层清理使用已有DOM引用，不在编辑器已关闭后再次调用owner.action|

夹具状态显示有100ms刷新间隔；若动作后立即读取到前一份Markdown，再读取最新状态确认，未把旧显示计作该动作已保存或通过。菜单标题和空列表的后续输入均来自内存状态，不以夹具输出冒充服务器回执。

开发配置关闭了HMR／WebSocket，控制台出现Vite客户端连接及发送错误日志；定位到@vite/client，与本轮正文动作没有关联，不宣称控制台无错误。补充Esc后重启本轮临时5179服务并重载夹具，核对最终代码。没有继续已取消的Node崩溃专项。

原有8000服务首页脚本引用与最终frontend/dist/index.html的资产一致（/assets/index-BO-nRamj.js），确认现有服务指向本轮构建。没有重启用户服务。

## 未覆盖与清理

没有对用户需求草稿进行编辑或真实保存验收；未扩大到完整自动保存／恢复、跨区块复杂选区、所有插入类型的全部组合、输入法实机专项、Mac实机键位、各浏览器及长文档滚动专项。macOS键位由metaKey分支提供，Windows短观察不冒充Mac验证。

停止本轮启动的5179临时服务，重置浏览器尺寸，关闭临时页签。夹具HTML／TS和mjs是可重复使用的测试输入代码；未保留测试输出JSON、截图、录像或原始日志。结果仅保留本Markdown。
