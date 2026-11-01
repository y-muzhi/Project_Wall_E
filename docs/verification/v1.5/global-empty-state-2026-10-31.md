# 全局缺省显示与新建文档展开助手检查

> 同日后续纠正：全站固定机器人及问句的规则是误实现，已由[M15-EMPTY-02按模块业务内容](../../archive/merges/v1.5/合并记录-2026-10-31-缺省业务内容.md)替代；公共布局、自检及助手显隐保留。下文描述和成绩仅属于原阶段，不改写成修正后的验证。

日期：2026-10-31。任务：M15-EMPTY-01／M15-CREATE-AI-01。HEAD33a6736；本轮在原未提交改动上增加前端公共缺省与目录成功后的布局联动，保留其他代码和v2.0文档。使用本机Node、现有锁定依赖／TypeScript／Vite／Prettier，没有安装新依赖。

## 当前模块自检

以下覆盖全部src TSX入口及相关命令／布局的空内容分支，属于源码／状态边界核对；公共DOM渲染及程序证据另列，不称每个页面均已浏览器验收。

| 模块 | 实现及本轮处理 | 加载／错误／恢复边界 |
| --- | --- | --- |
| 应用路由与详情首次读取 | application/app.tsx、requirements/detail.tsx核对 | 404、首次读取、失败和重新读取保留真实原因；不是成功空态 |
| 工作台 | requirements/workbench-view.tsx；空集合、无匹配和页越界统一EmptyState，删除重复新建按钮及旧空态样式 | 新建／筛选／分页原入口保留；加载／错误不显示空态，旧行保留 |
| 文档工作区 | detail.tsx的DocumentMount；未选文档、空CURRENT／历史显示公共缺省 | 真实宿主始终挂载，只切显示包装；人工空稿可输入，不改正文／ProseMirror，不把未加载文档判断为空 |
| 文档目录／无选择信息行 | document-directory-view.tsx；空目录／未选大纲使用紧凑组件，移除重复“尚未选择文档”和空工作区按钮 | 名称／元数据不伪造；无文档仍可访问信息行导航开关及导航＋；原MANUAL隐藏规则保持 |
| 正文大纲 | documents/navigation-view.tsx；已读取无标题使用紧凑组件 | 未读取／结构错误仍显示原状态，不伪造标题 |
| AI对话及消息 | messages/timeline.tsx；成功零消息显示公共缺省并按原阅读区居中 | 未读、加载、错误及定位回复状态保留；输入和消息owner不重建，不代发消息 |
| 修改建议 | guide/conversation.tsx无批次、suggestions/panel.tsx成功无可见项共用缺省 | 原批次、筛选、完成本批、未知请求及草稿保留；加载／错误不盖成空内容 |
| 评论 | comments/components.tsx无当前页项共用缺省；panel.tsx历史／零文档提供缺省 | 零文档仍有保留操作槽、业务／读取错误或加载时优先维持原状态与恢复；原历史不可写、人工／占用原因、读取错误及重试保持 |
| 版本记录 | 无阅读文档时detail.tsx直接缺省；已有文档成功空列表经RecordList | 未读／加载／错误与旧行分开；不额外请求或伪造版本 |
| 运行记录 | guide/read-view.tsx复用RecordList统一缺省，去掉自定义empty传参 | 筛选／页越界、原返回与运行详情／轮询归属保持 |
| 进展／主题／依据 | discussion-view.tsx；无主题、主题无依据、主线无主题分别复用标准／紧凑缺省 | 有主题但无焦点保留选择引导；真实主线、下一步与历史处置仍显示，不凭空生成内容 |
| 来源、请求／模型用量、分析结果 | source-reference.tsx、model-call-view.tsx、analysis-result.tsx、messages/model-return.tsx核对 | 缺失字段、未记录、程序未调用、取消、失败、无发现等是具体业务事实，保留真实语义和原文／读取入口，不变为页面缺省 |
| 表单／卡片／编辑工具／外壳 | composer-view、create_drawer、cards、manual-controls、headers、pagination、filters等核对 | 无可选文档／章节、必填／IME、占用、未确认请求、模态关闭及无内容工具隐藏沿原契约；不是独立空数据内容区 |

共享EmptyState只输出一个装饰图标及单行“我们要构建什么？”，没有说明、按钮、请求或焦点副作用。常规／紧凑及填充变体共享样式，已清理旧空态专属样式。AGENTS和正式FE加入未来新增／修改页面的初始加载、成功空、有内容、错误／权限、无匹配／页越界和恢复检查要求。

## 程序、渲染与构建

| 实际命令／方式 | 结果及范围 |
| --- | --- |
| npm run typecheck | 首轮发现另两处DocumentMount缺少显式empty参数，修正后strict类型通过；末次复查退出0 |
| node --test tests/detail-layout.test.mjs tests/v15-directory.test.mjs tests/requirements.test.mjs tests/messages-read.test.mjs tests/v15-discussion-presentation.test.mjs tests/record-list.test.mjs | 35项通过；记录／列表通用组件没有单独该命名测试，实际运行项为前五文件 |
| npm test | 440项通过；发生在最后“助手面板可见即保留任何页签”的判断修订之前，不冒充修订后的全量重跑 |
| node --test tests/detail-layout.test.mjs tests/v15-directory.test.mjs | 最后17项通过，覆盖全部页签可见时无发布／无偏好写入、隐藏展开保留页签／宽度、窄窗偏好打开但实际隐藏、BLOCKED、UNKNOWN原请求、CONFIRMED仅读取、较新阅读选择、元数据／失败／退役及一次性回调 |
| node --test tests/comments.test.mjs tests/comment-panel.test.mjs tests/comment-commands.test.mjs tests/v15-comment-guide.test.mjs | 末次补齐零文档评论缺省不能覆盖加载／业务／读取错误后，29项评论／恢复／权限相关检查通过；最终类型／格式和临时构建重新通过 |
| 一次性Node模块，经Vite middleware ssrLoadModule及react-dom/server渲染 | 4种EmptyState变体均1个svg／1个p及固定文案，无交互元素，装饰图标aria-hidden；RecordList成功空／页越界显示，未读／加载／错误不误显示，错误下旧行仍保留；服务finally关闭 |
| npm run format；npm run format:check | src按锁定配置格式化，最后全范围检查通过，未关闭strict或未使用检查 |
| node frontend/node_modules/vite/bin/vite.js build --outDir 临时目录 | 首轮系统沙箱Temp拒绝创建assets且清理报权限错误；复查该字面路径已不存在。改用frontend内TemporaryDirectory后1268模块、末次674ms、退出0；只有原大chunk提示，目录上下文清理完成，未覆盖frontend/dist |

目录CREATE仅在原完成读取／选择后回调布局；助手面板实际可见时任何页签保持原状，隐藏时沿原toggleRight展开。未知核实和确认后仅读取不重发创建，不自动Chat／计数／聚焦，不产生额外业务请求。

## 浏览器与清理边界

本轮启动独占5194隔离Vite（PID26768），临时页面只引入本轮组件和内存目录／布局，不调用业务API。IAB导航返回net::ERR_CONNECTION_TIMED_OUT，页面未打开，未取得视觉、点击或几何证据；没有换用Windows自动化重试。写入完成信号后Python finally结束所属Node，命令退出0；复查进程不存在、临时夹具目录不存在。SSR无需监听HTTP且已关闭；成功临时构建输出已清理。未保留截图、测试JSON、原始日志或脚本，未启动／重启正常8000／5173或操作用户文档。

最终未覆盖：真实浏览器区域居中／单行／窄窗布局、实际用户创建弹层到助手的端到端操作及多浏览器。不能由类型、SSR、440或末次17项推断页面视觉验收通过。原各专项未验证事项保持；本轮未做后端／真实供应方检查或提交推送。


## 文档与收尾静态核对

一次性Python解析本轮相关工作区32份Markdown的613个本地链接及目标锚点，缺失路径0、无效锚点0；新迭代已按原章节合入并归档，pending仅README。正式FE SHA256=4476460ea0215f835ad4720d66010c70a5483da9981ad624f9eced885d216132，与当前断点一致；BE摘要保持原值。旧空态专属类及重复文案已清理，frontend下本轮.empty-*临时入口0，git diff --check退出0。v2.0其他任务资料不纳入本轮检查或改写。
