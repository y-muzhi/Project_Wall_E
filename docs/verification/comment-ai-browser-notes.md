# 评论触发AI修改实际根验收

2026-10-07；tools/verify-comment-ai-browser.mjs登记8个独立根分支；tools/audit-comment-ai-browser.py独立只读关闭库审计。核对FE2026–2030/OP22，BE I34 5882–5924及C05完整2653–2730。真实人工输入、CURRENT3/Baseline1、公开I29 BLOCK/SELECTION评论。仅剥离配置的原生服务，无付费模型、正常库/8000变更。当前只证明I34真实用户TEXT/Run/范围/评论独立、原键未知恢复、在途保护和实际拒绝，缺模型时原生CONFIG_INVALID失败；后续SuggestionBatch根串联仍未证明，OP22保持实现中。

竞争前置在UI已发出本次意图而I34原生调用之前执行明确外部I31/I33/I09/I06，单独记录真实status/body。这样验证事务内拒绝，不把及时禁用的按钮强行当可发业务；不替换I34成功或失败响应。请求本身仅expected_content_version，不发评论复制正文或自拟Scope。未知202原键/原输入重放，只产生唯一USER TEXT和Run，取消未知编辑区保留原请求；接受自动打开AI页签，评论不自动解决。

原始范围/失败保留：
- comment-ai-browser-2026-10-07T08-55-24-769Z-75ef8563e8fd.json：BLOCK接受/未知两支通过，独立关闭库审计comment-ai-post-audit-2026-10-07T08-58-29.521657+00-00.json通过。当时452源字节不变；后续验证器扩充，用新版完整记录作为最终接受。
- comment-ai-browser-2026-10-07T08-57-20-348Z-e99cb5dd3fe8.json：SELECTION接受通过，下一已解决竞争在点击之前被页面及时刷新禁用，测试点击超时、没有I34请求。修正外部变更的明确请求边界时序，不修改正确权限保护。
- comment-ai-browser-2026-10-07T09-00-49-789Z-38dbeca64c1b.json：BLOCK/SELECTION/已解决三支通过，已删除分支原生STATE_CONFLICT409却被验证器错误期待404。原文C05 L2706–2707明确不存在才NOT_FOUND，已删除为STATE_CONFLICT；重新完整核对C05并修正严格409/具体code预期，不改产品或放宽错误类型。各失败自有服务关闭/源输入不变/0LLMUse。

最终结果继续追加，未闭合整条OP22、Provider兼容/效果或全项目。


最终完整8支接受/拒绝/未知/在途通过：comment-ai-browser-2026-10-07T09-04-18-925Z-5a19ee832b6a.json；452输入前后不变，原生服务正常关闭，0LLMUse；独立只读审计comment-ai-post-audit-2026-10-07T09-07-26.692558+00-00.json通过，关闭库字节不变。8需求/9文档/8Baseline/8评论（1明确外部删除墓碑）/12运行。四个接受分支各唯一USER TEXT与COMMENT/MODIFY_FROM_COMMENT Run（mode_snapshot=null），后端范围准确来自BLOCK/SELECTION原锚点；拒绝不创建消息/Run，外部前置变化分别核对，I34不改变原评论/CURRENT/版本。202只确认接受，最终原生CONFIG_INVALID失败且无模型批次。

实际BLOCK/SELECTION截图已查看：接受自动展开AI页签，原生缺配置运行快速FAILED时可能产生跨详情读取冲突，画面暂留已确认RUNNING/明确读取错误而不伪造FAILED。继续由verify-comment-ai-follow-browser.mjs验证显式“重新读取详情/刷新AI状态”后真实失败呈现；不能把上述8支直接称完整运行结果显示或OP22后续批次验收。

- comment-ai-follow-browser-2026-10-07T09-08-51-008Z-b88b0448c3a1.json：点击重新读取/刷新后已显示实际FAILED，但工具在异步AI刷新结束前立即断言旧错误不存在。诊断最终工具栏已可写/原生GET成功，改为等待实际错误隐藏及刷新结束后核对，保持错误必须清除与实际失败呈现要求，不修改产品。

comment-ai-follow-browser-2026-10-07T09-11-12-646Z-bd9a18ddc530.json两支原生失败显示及AI错误清除通过，闭库审计09-12-46.922394+00-00通过。截图仍有独立父面板读取错误，原文详情面板维护独立错误/重试；继续补父级“重试”后错误清除，不能将AI状态刷新当所有父级错误自动清除。产品未修改。

- comment-ai-follow-browser-2026-10-07T09-13-49-978Z-8adce98ec22e.json：BLOCK连同父面板重试清错通过；SELECTION业务函数启动前遭CLI命令行长度限制（退出1），独立库/服务正常关闭/0LLMUse。专用跟踪工具去掉不属于两支范围的生成拒绝/未知分支，缩短实际传输，不改产品、断言或CLI环境，也不开展Node崩溃调查。


最终两支真实跟踪/读取恢复通过：comment-ai-follow-browser-2026-10-07T09-15-50-680Z-b4672623e30c.json，独立关闭库审计comment-ai-post-audit-2026-10-07T09-17-13.692564+00-00.json通过。真实重新读取详情、刷新AI状态与必要的独立父面板“重试”后，AI显示原生FAILED/CONFIG_INVALID、先前读取冲突与父面板错误清除，保持用户TEXT/评论/完整CURRENT/版本。4条初始/恢复原始截图均已查看，原字节/SHA保存header-media相应两会话；恢复的选区图在父面板重试引起下一正常AI读取时取图，保留真实加载文字，不宣称所有异步读已完全静止。没有新增模型或业务重复提交。

8支与2支是不同前置/验证目的的独立根页，共10条接受及读取恢复分支；各验证器与其452源前后不变，生产/共享夹具公共451一致且分别独立审计。OP22后续模型SuggestionBatch实际根串联仍待；保持实现中。没有修改I34业务实现，新增验证工具/范围与证据不算新增业务功能。
