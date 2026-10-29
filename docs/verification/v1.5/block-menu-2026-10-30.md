# 区块左侧操作菜单检查

日期：2026-10-30。M15-BLOCK-MENU-01。仅前端导航／浮层／评论入口和样式；上一新建入口未提交修改保留。

已通过：

- `npm run typecheck`退出0；选区状态初始化修正后再次类型检查退出0。
- `node --test tests/navigation.test.mjs tests/comments.test.mjs tests/comment-panel.test.mjs tests/selection.test.mjs tests/selection-toolbar-position.test.mjs tests/editor-interactions.test.mjs tests/v15-reading.test.mjs tests/detail-layout.test.mjs`：8个既有文件通过，0失败，1309.359108ms。
- Chromium154.0.8037.57隔离页面使用真实RequirementEditor、DocumentNavigation、BlockAuxiliary、CommentDocumentTools及CreationEntries。内存快照来源为既有fixtureDraft／实际解析器，评论panel只记录已验证目标、不提交业务写入。1440×900下正文x349、按钮x313，按钮与文字有独立间隔；悬停显示唯一高亮及按钮，按钮移入展开左侧菜单，菜单恰好2项，鼠标可跨越间隙进入菜单。移出后收起并清除高亮。
- 菜单方向键及按钮ArrowDown导航通过；来源实际打开、Esc只关来源后再关菜单并返焦点；点击展开通过。来源打开期间目标锁定沿Navigation。区块评论目标为Block2／BLOCK，独立选区评论为Block3／SELECTION，原commentTarget快照校验真实执行；禁用后评论不可提交。未调用真实CommentCommand或后端，不称完整评论保存链通过。
- 列表作为真实顶层区块高亮；滚动使区块离屏后入口隐藏；setVisible(false)和dispose清理入口与高亮；CURRENT文档内容及MANUAL_DRAFT ledger快照保持不变。人工草稿来源说明实际显示、评论禁用；compositionstart后导航无效并收起，compositionend恢复。
- 560×750下菜单不足左侧空间改在按钮下方，测得x49／y234／160×82px，夹在可视范围且无页面横溢。页面脚本错误0。

补充检查：第一轮真实编辑器主链通过后，提高代码／表格类高亮选择器优先级，并补查键盘、纯悬停移出及滚动离屏边界；第二轮上述记录通过。未将第一轮重复计算为新增覆盖。

构建与清理状态在下方收尾记录补记。未启动业务服务、写用户数据、调用模型或提交推送；未留截图、录像、JSON或原始日志。未重新验证完整历史版本恢复、评论后端写入、真实IME、多浏览器和整版验收。

收尾：临时Vite生产构建1262模块，1.20s退出0，仅既有大chunk提示；临时目录由trap删除，frontend/dist未覆盖。隔离Vite／浏览器通过finally关闭，缓存及work临时脚本已删除。最终`git diff --check`与修改Markdown本地链接核对通过。
