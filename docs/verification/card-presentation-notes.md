# 卡片显示、可读降级与真实等待回归（2026-10-07）

重读前端正文 L1325–1356、BND-CARDS L1572–1591，以及正式卡片来源/回答归属；本批只修改 messages/timeline.tsx 与 guide/card-message.tsx 的展示。原 C07 产生的有效 INTERACTION_CARDS 曾重复展示 canonical 协议字段段落和实际卡片；现在正常结构交给真实卡片 owner 显示引导语/问题，结构缺失、未提供渲染器或来源首次读取失败时保留实际可读 content。首次源失败无未验证输入控件，独立重读成功恢复原 sessionStorage 草稿；没有修改存储原文、公开字段、正式答案、v2等价算法或批准资源。

[固定最终四根](card-presentation-browser-2026-10-07T14-34-32-419Z-08a5b0866bb4.json)与[独立闭库审计](card-presentation-post-audit-2026-10-07T14-42-29.058274+00-00.json)全部通过。TEXT-normal、CARDS-normal、CARDS-source-error、CARDS-unknown 均由实际生产根页面/HTTP/SQLite及明确本机受控TCP返回产生 WAITING；没有SQL安装卡片/结果。来源失败用真实 I35 已读到卡片后的 I16 读请求拒绝，保留实际读失败及父级错误；不伪造返回值。失败段落的 innerText、textContent、真实浏览器接口正文和闭库原文逐字一致，pre-wrap。重读恢复自定义原稿、零默认推荐、重复协议段落消失，随后真正I15同Run续轮，EXPIRED以后才清本地。未知首次202实际提交后丢回执，保普通输入与卡片稿，原键/原body/原data重放，只一条USER补充/无CARD_RESPONSE。完整CURRENT3及Baseline不变，最终IDLE。4需求/4CURRENT/4Baseline/8Run/8真实LLMUse/8本机Chat/0建议/0付费，私有编译预算与兼容回调不是Provider证明。

[实际四卡组件/读取几何回归](cards-browser-2026-10-07T14-33-07-653Z.json)与[独立闭库正式答案/持久回执审计](cards-regression-post-audit-2026-10-07T14-41-07.655275+00-00.json)通过。来源卡片可用性为明确持久测试前置，不能冒作模型产出；后续I36/I15/I35是正式真实实现。逐卡错误真实焦点、存储不可用恢复、reload原稿、初始化新Run/等待同Run、整组丢202原键、确认后仅读、不同键409与正式答案唯一、后续CONFIG_INVALID不撤回答案、普通文字导致EXPIRED均通过。异步源展开前height1017/top657/距底0，展开后4801/4441/0；multi阅读偏移7.5625→7.390625，误差0.171875px。2需求/2文档/1版本/6Run/0LLMUse。457输入不变，与根451公共输入完全相同。根452输入不变，与上一批451公共输入仅两展示文件变化，见 card-presentation-combined-2026-10-07.json。

[前端263项＋独立4 development/TS/依赖](frontend-2026-10-07T14-14-07-700Z.json)在本批修正后通过，当前全部输入hash一致；正常生产构建实际退出0。原8000只读检查连接拒绝，监听清点为空；恢复既有授权单进程预览launcher50964，过滤WALLE模型环境，不载入.env。PowerShell环境移除式启动被自动策略拒绝，未执行；改用显式过滤子进程环境的隐藏Python启动成功。随后辅助健康查询误加未支持page_size，被真实422拒绝；改用正式I01无额外字段后页面与接口200、HTML等于新dist，正常数据库SHA跨恢复一致。两项失败原样保存 preview-failure/preview-query-failure 报告及工具输出，最终见 card-presentation-current-preview-2026-10-07T14-38-43.056226+00-00.json。没有调查Windows崩溃。

全部四份浏览器失败保留：14-11重复字段是实际产品缺口；14-14故障太早拦截全部I16、连初始详情都读不到，是验收前置错误，修正为实际I35卡片已到后拒绝来源读取；14-21/14-30跨CLI命令的嵌套转义把预期content_snapshot里的字面\n误变换，实际DOM内容及pre-wrap正确。改为从真正浏览器HTTP响应获取预期，再在Node端及闭库核对原文，未放宽逐字断言。单支14-32及其独立审计保留，固定四支最终全部通过。27张全部阶段原图和SHA保留 card-presentation-media/manifest.json，已查看正常、失败、恢复及真实阅读锚点原图；失败图中父级来源错误如实保留。unknown图已采用实际session命名，未改变旧批报告。

373原始正式行身份/六列不变，44已验证/311未开始/18实现中，不等于实现百分比。既有814后端/55核心沿原证据范围，未称本批重跑。本批完成展示/来源失败边界，完整卡片场景的1/5、初始化实际生成、ASK/REVIEW/MODIFY整组正式答案、冲突/取消/迟到，PERSISTING竞争/根重试及其余正式场景仍待。真实IME/键盘与正式DeepSeek计数兼容/效果仍独立未闭合，0新增付费，不宣布整个项目完成。

下一单元已重读 FE OP02 L732–747、BE SHR-CARDS L446–487、C06 L2734–2830、I36 L5969–6018：从本机受控实际C07生成的ASK卡片，通过根页整组提交及原键未知恢复，独立核对唯一CARD_RESPONSE、同Run call_no2、正式答案/原问题上下文与Manifest。现私有ControlledScopeModelWorker只识别“操作范围验收 ”普通trigger；CARD_RESPONSE可读摘要不带前缀，需明确私有来源证明后才允许受控第二轮，不能通过默认匹配/真实密钥绕过。生产算法不变，模型仍0付费。之后推进其它动作等待与根取消/重试。保存前读取当前工具与上下文完整契约，不修改已批准资源。
