# 人工编辑区块与选区交互检查

日期：2026-10-30。M15-EDITOR-SELECT-01。代码基线HEAD33a6736加本轮前端修改；开始时实现进度已有服务启动记录变更，已保留。正式FE／BE摘要未改。

静态诊断：原DocumentNavigation直接修改ProseMirror区块class；本地prosemirror-view的DOMObserver.registerMutation将节点属性变化作为文档范围重读，普通NodeViewDesc不会忽略此变化。新实现改用宿主作用域外置样式，不再修改正文节点；格式与评论的原校验／事务入口保持。没有把源码诊断当作旧版浏览器复现证据。

离线检查：

- `node node_modules/typescript/bin/tsc --noEmit`通过；首次临时检查夹具的document_type推断过宽报错，改用既有DocumentReadModel后通过，产品类型规则未放宽。
- `npm run format:check`通过，src全部使用锁定Prettier配置。
- `node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/*.test.mjs`：424通过、0失败，5477.4538ms；网络连接由离线预载阻止。
- 新增selection-surface.test.mjs的4项覆盖左键期间抑制、外部松手／取消、键盘选择／销毁、共同视口边界及高亮作用域。初次定向54项中53通过、1失败：Node EventTarget对布尔capture参数的移除行为使清理断言失败；改为显式同一capture选项对象后4项及上述424项通过。

浏览器：仅本机5191隔离Vite与内存DocumentReadModel，使用真实RequirementEditor／DocumentNavigation／BlockAuxiliary；未连接API、存储、自动保存或模型。初次导航自动审批因模型容量不足而未执行；用户明确允许重试后，受限进程页面连接超时，改为获批的本机检查进程后已连通。错误页恢复受浏览器data URL策略限制；通过文档允许的新检查页恢复，未访问外部地址或绕过证书／安全提示。

已观察人工编辑：正向拖选后原生与编辑器文本／范围一致、changes=0；浅蓝计算样式rgb(237,242,255)，正文区块class保持空；六点坐标为3／8／13×5／11。点击选区加粗保留原选区，只有选中文字增加strong且changes=1；反向跨段拖选保留原文及同一changes计数，选区浮层显示。最新代码的检查页再次正向拖选，popupDuringDrag=0且changes=0；进入六点菜单后仍蓝底、原选区不变，人工草稿评论按钮保持禁用。

阅读页使用真实CURRENT只读RequirementEditor及CommentDocumentTools，panel／document订阅仅为内存夹具。反向同区块拖选后popupDuringDrag=0、changes=0，只有评论浮层，无格式浮层；点击后实际commentTarget验证通过，目标为document90／content_version3／block2／SELECTION，选区0—24且quote及前后文一致。跨段反向拖选后评论浮层为0，正文无变化。没有向真实CommentCommand或API提交评论，不称后端评论保存已验收。

浏览器日志观察到隔离配置关闭WebSocket后的Vite客户端连接及上报错误；所查日志无本轮产品异常，不能称完整控制台零错误。禁用HMR及watch后测试服务重启一次再加载最终源文件，未把缓存页面作为最终代码证据。

生产构建：通过Python TemporaryDirectory执行`node --require ../tools/quality_node.cjs node_modules/vite/bin/vite.js build --outDir <临时目录>`，1264模块、635ms、退出0，仅既有大chunk提示。第一次选择沙箱系统临时路径时Rolldown写入被拒且Python清理同样被拒；改在workspace/frontend下创建受控随机目录后构建成功并在finally清除，未覆盖frontend/dist。随后以提升权限的精确空目录检查清理首次失败路径，检查退出0、目标当时未存在，无删除业务文件。

收尾：所属5191检查进程已结束，正常用户服务未启停；成功检查页已关闭，初次连接错误页由工具按回合清理。临时HTML／TSX夹具已删除，产物只保留本Markdown及输入回归测试。未验证用户实际业务会话、后端评论保存、真实IME、多浏览器或整版验收；不能以离线或内存交互代替这些证据。不留截图、录像、JSON报告或原始日志。

最终复核：移除临时夹具后`npm run typecheck`及`npm run format:check`通过；`git diff --check`通过（README仅行尾转换提示），本轮修改／新增Markdown互链无缺失。`python tools/cleanup-test-artifacts.py --dry-run`显示JSON=0、screenshots=0；临时夹具及workspace构建目录均不存在。

用户后续更正（2026-10-30）：六点图标应为两列三行。仅将Icon.blockActions的横坐标改为5／11、纵坐标改为3／8／13，同步专项、映射与当前断点。`npm run typecheck`、`npm run format:check`及`git diff --check`通过；此小幅图标更正未重跑浏览器、业务测试或构建，上述浏览器坐标保留原观察，不作为新排列的浏览器证据。
