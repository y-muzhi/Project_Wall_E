# 前端实施边界

已按D-003安装精确依赖，完整传递依赖锁定在package-lock.json。当前包含选区辅助函数、真实Crepe源码/身份适配和本地编辑快照输出；业务页面、路由及HTTP尚未创建。

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

source-nodes.ts在create前安装，保留重复引用定义及惰性HTML文本节点、行内图片alt、代码尾换行；关闭会删除定义/改变HTML类型的默认插件、自动尾段和临时blob上传。editor-source.ts将原文片段、空白gap、初始节点、投影和章节路径同时绑定。unchangedMarkdown仅在真实节点未变化时返回原文，编辑后拒绝返回旧源码；不能用Crepe.getMarkdown替代源码保存。编辑后的输出由edited-snapshot.ts处理，应用接入仍待实现。

浏览器验证脚本使用Playwright CLI技能包装器（Windows需Git Bash及npx；可用WALLE_BASH/WALLE_PLAYWRIGHT_WRAPPER指定路径），在独立5174端口启动测试探针，使用自己的浏览器会话并在结束后关闭。15个独立共享样例覆盖11类型、CRLF、重复定义、图片、代码尾行、空文档、未闭合/未注册语法；断言真实节点投影、原文保留、编辑拒绝旧源和HTML不执行。原始输出存docs/verification，截图存output/playwright。手工探针可在本目录运行`node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173`后访问`/tests/browser/editor.html`，它是测试工具。

这些验证不证明产品布局、焦点、滚动、IME、自动保存或完整方言边界，373项设计场景仍未执行。尚未提供业务页面启动命令。

identity.ts安装顶层节点walle_block_id属性（不进Markdown）、初始显式绑定、StepMap原节点继承、新插入/复制新ID、拆前保留/合首保留、显式整体移动、同编辑器真实history恢复及高水位。未知粘贴不信任携带ID，内部节点清除顶层身份；空文档caret不分配业务ID，容量失败不改原状态。空段落边界合并优先执行真实join，避免通用删除把首个ID丢弃。属性修正只setNodeMarkup，保留光标与history；位置二分查找，未变节点复用。当前13项身份测试，加7项选区共20项；浏览器额外核对全部15例身份属性/DOM与10步真实键盘。它仍不是完整编辑器：尚缺来源/草稿应用绑定、选区DOM映射及生命周期。

空白边界：新空段落只作gap，不预占ID；输入正文后分配。已有拆分前段身份保留；含gap的显式移动跳过空gap的来源声明。验证Vite禁用HMR，源码/探针/夹具/lock/验证工具前后哈希一致才判通过。早期热更新中断的失败证据保留。

contracts.ts校验DocumentReadModel与BlockState全部字段、正安全整数/独立版本、严格UTC日期/时间顺序、D-008署名组合、唯一ID/高水位、11类型和实际Markdown章节路径对应、4MiB容量，返回与输入隔离的冻结数据。结构校验不证明来源对象关系或授权，后端仍需同事务验证。真实浏览器另外覆盖15合法样例、31拒绝变体、四种非模板组合、外部变更隔离和容量拒绝。

edited-snapshot.ts的EditedSnapshotLedger只接受完整MANUAL_DRAFT与同次绑定的实际EditorState；按已证明ID保留未改源码，使用单块序列化处理编辑，并在输出前完整重解析，拒绝吞块/合块或丢内容。已有创建信息保留，原文/章节路径变化更新人工署名，新块来源为输入草稿ID；返回冻结的完整Markdown/BlockState本地对，不包含持久化成功或新版本。

源码账本区分原始gap与生成的分隔符；同会话完整节点历史可恢复原始布局，撤销不累积空行，next不回退。空caret不填造Block，失败不改变账本。原始HTML/定义节点编辑必须仍能对应其实际节点类型与一个顶层区块；完整组件还须处理重新分块/类型转换及视图同步，不能把目前拒绝的局部状态标为已支持。账本缓存的生命周期与资源控制也须在RequirementEditor接入时处理。

最新浏览器覆盖19项编辑输出行为和10步键盘逐字源码，tools/verify-editor-output.py将其中实际输出与后端真实解析器/结构校验比较，共49对快照通过。该工具只使用测试来源，不证明真实会话数据库关系、HTTP保存或完整编辑器验收。证据：docs/verification/editor-browser-2026-10-03T12-59-47-413Z.json；源码/工具/夹具等16项输入前后hash一致，浏览器及Vite已关闭。

自动链接生产规则使用原始源上的micromark tokenizer，保留表格/任务/删除线并处理真实表格chunk与转义竖线，不靠实体解码后替换AST文本。专项运行`node tools/verify-editor-browser.mjs --autolink-check`：48个独立预期与3个真实编辑后的输出，51对完整快照交给后端验证。完整默认模式再运行原编辑/身份/键盘及输入门禁，共100对；最新证据editor-browser-2026-10-03T14-08-31-198Z.json，29输入前后hash一致。24项独立前端测试及TS通过，另在development条件运行4自动链接测试以覆盖Vite使用的解析器断言。

`--autolink-baseline`仍只采集当前22例，BASELINE COLLECTED不表示合规；修复前5处前端/16处后端差异的历史证据不覆写。原源及星号/协议边界修复已验证上述有限范围，Unicode域、更多括号语境、GFM其他边界和完整组件仍待补齐。详细记录docs/verification/autolink-baseline-notes.md；没有产品页面启动命令。

单双删除线另有18独立例，专项运行`node tools/verify-editor-browser.mjs --strikethrough-check`。inline-marks.ts在生产sourceRemark中展平重复delete样式，避免Milkdown关闭内层时把外层剩余文字漏划；原始tildes由源码层保存。21对专项输出与完整模式121对通过后端校验，最新editor-browser-2026-10-03T14-30-29-473Z.json，33输入hash不变；25前端测试/完整TS通过。不表示全部键入规则或产品视觉验收通过。

Unicode域名单元：shared/markdown/url-domain-unicode-v1.json冻结所选Python3.13/Unicode15.1的748字母数字区间，url-domain-unicode.ts按完整码点查询。实际Node的Unicode17分类不直接作为业务语义；生成工具拒绝覆盖，后端升级需重新逐码点验证。新增8独立例及2真实编辑输出；自动链接专项现为56例/61对，默认完整模式131对，最新editor-browser-2026-10-03T14-54-25-426Z.json的36输入hash一致、会话关闭。27项前端测试及完整TS通过，后端123项；两端均核对全部1,114,112码点。上述历史证据保留，Unicode域列出范围已验证；嵌套原始节点、更多标签边界、完整组件仍待实施。

容器内原始HTML/定义由raw-source-remark.ts读取真实流片段，去除容器前缀但保留原始换行/缩进/转义；source-nodes允许合法块作为列表首项（生成空列表仍优先段落），不补空段造成投影变化。后端按块树连接，嵌套表格保留TAB/LF结构。专项`node tools/verify-editor-browser.mjs --raw-source-check`现为18独立例/22对输出；默认完整模式153对，editor-browser-2026-10-03T15-35-41-838Z.json，40输入hash不变、会话关闭。125后端/28前端/TS通过。更多键入/列表命令、原始节点重新分块、DOM选区和完整组件仍待验；上述有限范围不等于全部GFM。

editor-selection.ts正向适配真实EditorState与原生DOM端点，映射到selection.ts的共同码点事件；只接受同一实际Block及精确往返端点，拒绝代理项内、部分原子HTML文本、跨块/编辑器外、迟到DOM和2001码点。折叠选区不发正文事件。文档id/version由父级同次载入上下文传入，父页面控制仍待实现；反向定位见下述追加记录；它不认定保存或授权。专项`node tools/verify-editor-browser.mjs --selection-check`覆盖12独立正反向黄金例、2000码点和真实键盘emoji，共14记录；后端真实锚点重新定位起止一致。完整模式167对快照、44输入hash不变、会话关闭，editor-browser-2026-10-03T15-55-02-644Z.json；125后端/28前端/TS通过。

反向定位使用editorRangeForSelection/locateEditorSelection，先核对事件版本/区块/原文，再定位TextSelection或完整代码NodeSelection，不猜测原子内部或部分虚拟尾行。验证完成前不改选区/焦点/滚动；旧document/版本/改文/缺块及不能表示的端点拒绝时状态对象不变。专项现为15合法记录（14原生DOM文本往返、1真实代码块选中样式）、12拒绝及折叠null；默认168对，editor-browser-2026-10-03T16-08-29-798Z.json，44输入hash一致、会话关闭。28前端/TS通过，125后端基础证据仍有效；新的15范围全部经真实后端锚点定位。它尚未接父页面生命周期/历史隔离/HTTP定位事件，不等于完整组件验收。

顶层原始节点重解析使用normalizeRawSourceBlock生成暂存状态，调用EditedSnapshotLedger.capture(state, at, normalization)完成全源码预检，成功后才view.updateState。首块保留ID，额外块取新ID；空白/删除/分块使用实际事务及history恢复。私有walle_source_revision根属性区分相同富文本但不同原文的撤销记录，不序列化到Markdown或公开字段。专项`node tools/verify-editor-browser.mjs --normalization-check`覆盖16检查/21实际输出；默认189对通过真实后端校验，editor-browser-2026-10-03T17-26-06-642Z.json的46输入hash一致并关闭会话。28前端测试及完整TS通过，125后端基础证据未变。此适配仅覆盖显式顶层原始节点；嵌套原始节点、跨块引用上下文、完整组件及真实会话/HTTP/DB保存仍待实现。

normalizeRawSourceBlock现接受包含原始子节点的实际引用/列表，按完整容器源码解析，要求仍为同类型单个顶层块；不把内部新段落分配顶层ID。新增7检查/21对实际输出，核对未编辑定义CRLF、富文本兄弟及真实undo/redo；专项合计23检查/42对，完整210对通过，editor-browser-2026-10-04T03-07-39-396Z.json的46输入hash一致并关闭会话。28前端/完整TS通过。外部引用定义与跨块上下文尚需全局重绑定；上述范围不表示完整编辑器或持久化验收完成。

完整源引用上下文使用账本prepare(state, at, normalization?)，它只生成独立预检与重绑定实际EditorState；调用者view.updateState(prepared.state)后以accept(prepared, view.state)发布对应pair。跨账本、伪造、状态错配、过期和重复accept均拒绝。真正appendTransaction使引用派生变化与定义编辑共同undo/redo；原有空caret保持，未编辑引用源码不改写。新增9检查/21对，专项32项/63对、完整231对通过，editor-browser-2026-10-04T03-23-11-919Z.json的46输入hash一致且会话关闭；28前端/完整TS通过。常规容器序列化仍可能把内部兄弟引用改写为旧地址inline链接，下一步须按实际源位置保留这些写法；跨块边界及完整产品组件/HTTP/DB保存仍开放。
