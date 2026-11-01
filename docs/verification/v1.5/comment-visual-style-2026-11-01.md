# 评论原文高亮与卡片视觉检查

日期：2026-11-01。M15-COMMENT-STYLE-01；HEAD33a6736上的未提交工作区。用户飞书截图是视觉参考，先写[独立迭代](../../archive/iterations/v1.5/WALL-E.评论原文高亮与卡片视觉优化_V_1.5.md)，再实现7个源码文件；本轮不合入正式设计，原其他改动及v2.0资料保留。

## 实现与代码检查

- comments/highlights.ts为每个文档拥有独立CSS HighlightRegistry名称及样式，基于全量I37当前位置和既有严格选区投影生成Range；未解决浅黄、当前／草稿金黄、选中已解决柔和绿色，失效／旧版本／人工草稿不涂色。clear／destroy只清理所属范围，缺少API时安全保留原标记／定位；逐项add避免大评论集合展开为构造参数。
- components.tsx／panel.tsx接入真实评论与待创建目标；使用既有editorReadModel规范正文身份比较，DocumentView的name／archived_at等元信息不再导致相同正文被判不一致。此修正也用于既有数量标记，仍检查当前文档、版本、正文及BlockState，不放宽定位校验。locate.ts继续原选区定位、章节展开和滚动；选中原文由评论暖色标注负责，不再叠加通用黑色定位边框。
- 卡片／引用／状态、数量标记、区块／选区入口、AI设置及全部评论按钮使用同一配色体系。右上更多为不撑开卡片的菜单；支持初始焦点、方向键循环、Home／End、Esc返焦点和外部关闭。添加／保存／建议为蓝色主按钮，取消为白底次按钮且位于提交左侧，删除为危险色并保留原确认。没有伪造作者数据或改变命令许可／范围／原请求恢复。
- 最终frontend下`npm run typecheck`、`npm run format:check`均退出0。所有写入均在内存完成内容／锁定Prettier格式化，同目录临时文件fsync／关闭、并发复核后原子替换，没有直接截断原源码。
- 最终`node --test --test-reporter=dot tests/comments.test.mjs tests/comment-panel.test.mjs tests/comment-commands.test.mjs tests/selection.test.mjs tests/selection-surface.test.mjs tests/selection-toolbar-position.test.mjs tests/v15-comment-guide.test.mjs`退出0，43项通过。覆盖既有评论创建／编辑／解决／重开／删除、UNKNOWN原请求与范围、确认回执／读取失败、分页／失效、Unicode选择与工具栏边界；新视觉另由下述浏览器证据验证，不以原专项代替。

## 当前服务与独立浏览器

当前5173六个模块的内联source map与最终磁盘源码逐一一致，实际导出存在：highlights.ts16451字节、components.tsx39172、panel.tsx64273、command-control.tsx30336、locate.ts5182、shared/icon.tsx26010；shared/styles.css返回新调色板及按钮规则。没有仅凭HTTP200判断正常。独立Chrome最后只读打开/requirements/1，详情及Ai助手入口实际出现。

使用真实RequirementEditor、CommentPanel和CommentDocumentTools，配合内存中的3段中文／富文本／emoji正文及21条评论，当前分页20条；没有向业务API发评论写请求或真实模型请求。临时预览由原5173提供，不启动测试HTTP服务。

- 实际集成渲染正常，分页之外第21条评论原文仍高亮；粗体“重点原文”4码点和emoji单码点Range准确。正常、活动、选中已解决、待创建标注分别核对；失效／隐藏区块、旧版本及人工草稿排除。
- 纯高亮前后ProseMirror文档JSON、DOM HTML及原生选择JSON完全相同；无事务或正文Mark。模拟无Highlight API时不报错，清理后不遗留所属Registry项。
- 卡片更多打开前后高度差0px；删除文字rgb(166,49,38)，提交背景rgb(54,94,220)／白字，取消白底，取消位于提交左侧；动效结算后提交按钮位于输入卡片内。临时截图已实际查看，确认原文黄色、卡片强调条、引用层次、白底取消和蓝色提交显示正常。
- 草稿emoji高亮在输入失焦后保持；取消新建及编辑操作成功关闭对应编辑区；1060px视口下菜单不越界。Home／End、触发按钮ArrowUp到末项、ArrowDown循环、Esc及外部关闭通过。
- React卸载后评论Registry项为0。最终两轮完整／键盘定向浏览器Console错误0、警告0；正常需求页能启动。未把隔离数据的视觉检查表述为正常库写入或真实模型效果。

## 发现、修正与未覆盖

首轮临时夹具日期缺少UTC毫秒，预览未就绪；核对契约后仅修正夹具为合法时间。静态核对发现完整DocumentView与编辑器正文投影的整体JSON比较会误判附加元数据，已按上述规范投影修正，并用带name／archived_at的真实形状夹具验证。初次预览只有临时/favicon.ico的404，改为内嵌空图标后最终Console为0。截图必须等待原展开动效结算再判断提交区是否完整，末次已检查真实按钮几何；原公共动效未被绕过。

所有所属浏览器会话close退出0，临时源码／HTML／快照／截图／日志均清理，仅留本Markdown。未运行生产构建、全项目、多浏览器或真实供应方；强制颜色模式仅实现CSS回退，未作实际操作系统验收。页面空／错误／历史沿原分支，相关读模型与恢复专项通过，未新增这些页面的正常库端到端操作。不启停用户8000／5173、不修改正常正文／评论／占用、不提交推送。

正式FE SHA256保持2039cbe1e3cf5f80c9b39f40b799cfa07ae8c3633a1c6f92d84362e7c64b9b48；BE保持8c7bad2949d4258b37296e99d06e3747bea7e209c72974168989d749cbd8220f。收尾实际核对8份文档／369条本地链接与锚点通过，当前断点唯一，原子临时文件及预览源码／截图／日志产物0，git diff --check通过，HEAD仍33a6736；迭代继续pending。
