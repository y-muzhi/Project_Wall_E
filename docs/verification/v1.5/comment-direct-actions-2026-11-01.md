# 评论直接操作与解决后隐藏检查

日期：2026-11-01。M15-COMMENT-ACTIONS-02，HEAD33a6736的未提交工作区。先写[独立迭代](../../archive/iterations/v1.5/WALL-E.评论直接操作与解决后隐藏_V_1.5.md)再实施；正式设计本轮不合并，原其他改动与v2.0资料保持。

## 实现及离线

comments/read.ts增加resolved_revision及hideResolved，只对同一已确认CURRENT中RESOLVED目标发呈现信号，清理已解决选择，不过滤或改写confirmed items／index／pagination。panel-owner.finish在原回执CONFIRMED且真实adoption／列表读取成功后调用；别人已重开则不隐藏。列表按本页真实行分组，已解决默认折叠；有保留操作槽的行优先保持可见，显式定位已解决时展开。只读信号不是内容版本或新的HTTP字段。

panel.tsx去掉评论更多、菜单及专属键盘／外部监听；右上为解决并隐藏／编辑／删除直接图标，AI建议底部可达，原确认／范围／恢复继续复用。components.tsx实现已解决区、本页空态与关闭逻辑；command-control.tsx同步解决操作文字。styles.css删除旧comment-more-trigger／comment-more-actions规则，增加图标工具条及已解决折叠样式。没有新增后端接口、真实调用或正文变更。

- frontend下`npm run typecheck`及`npm run format:check`退出0，strict及格式通过。
- `node --test tests/comments.test.mjs tests/comment-panel.test.mjs tests/comment-commands.test.mjs tests/selection.test.mjs tests/selection-surface.test.mjs tests/selection-toolbar-position.test.mjs tests/v15-comment-guide.test.mjs`46项通过；末次相同集合以`--test-reporter=dot`再次退出0。新增3项实测：隐藏信号不改真实页／索引及拒绝OPEN／旧文档；UNKNOWN和确认后GET失败不隐藏、原请求确认及GET恢复后才隐藏；新索引已重新打开则保持OPEN。
- 测试新增内容沿原文件风格，comment-panel.test.mjs保留其CRLF；src在内存按锁定Prettier格式化。所有文件同目录临时写完fsync／关闭、复核未并发修改后原子替换。

## 当前5173与浏览器

现有5173实际模块source map与磁盘一致且运行导出存在：comments/read.ts34264字节、panel-owner.ts48360、components.tsx46583、panel.tsx58710、command-control.tsx30357；CSS含直接工具条／已解决区且无旧更多菜单。最后独立Chrome只读打开/requirements/1，详情实际启动。

隔离预览使用真实编辑器、CommentPanel及内存中21条评论／本页20条；所有命令只更新内存对象，无正常库写入或模型请求。360px评论面板中：

1. 每条未解决卡片右上3个直接图标，解决按钮无可见文字、aria-label／title均“解决评论并隐藏”；更多按钮及旧菜单DOM均0。图标边界均在卡片内，临时截图已查看后清理。
2. 直接编辑可填写并取消；直接删除打开原确认，保留评论后无删除写入；AI建议入口可直接打开范围设置并取消，没有模型调用。
3. 解决成功后卡片不可见、选择清除，索引仍有真实RESOLVED行且总数21不变；可展开已解决区并重新打开，卡片返回展开区。已解决区本来展开时再解决，也会关闭折叠区并隐藏目标。
4. 模拟已执行但回执丢失，UNKNOWN保持可见；再读到RESOLVED仍因保留槽可见。核实只准备原命令1次、执行2次，原回执确认及真实读取后才隐藏。
5. 模拟解决回执确认但列表GET失败，卡片与“重新读取评论与详情”保持；读取恢复后隐藏，解决写次数不增加。当前页全部解决但其他页仍有未解决时，显示“本页暂无未解决评论”；第2页的未解决评论仍可达。
6. 明确拒绝解决时卡片保持可见，可取消本次操作恢复直接按钮。卸载后评论HighlightRegistry=0；正常需求页启动通过，最终Console错误0、警告0。

## 清理与边界

本轮浏览器无失败；只有内存夹具的预期UNKNOWN／GET丢失／拒绝用于边界检查，不是正常业务数据故障。所属浏览器close退出0，临时预览源码／HTML／截图／日志清理，无测试JSON或原始日志留存；未新增HTTP测试服务、未启停用户8000／5173。未跑生产构建、全业务、多浏览器或真实供应方，不把隔离回执当作正常库写入验收。旧视觉迭代的菜单及常驻已解决规则由本迭代替代，旧43项成绩保留原批次意义。

正式FE SHA256仍2039cbe1e3cf5f80c9b39f40b799cfa07ae8c3633a1c6f92d84362e7c64b9b48；BE仍8c7bad2949d4258b37296e99d06e3747bea7e209c72974168989d749cbd8220f。收尾实际核对9份文档／380条本地链接与锚点通过，临时产物0、当前断点唯一、旧更多菜单不存在；git diff --check通过，HEAD仍33a6736。独立迭代继续pending。
