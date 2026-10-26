# WALL-E 进度依据引用Schema约束修复 V1.5

2026-10-24（客户端日期）。本修复依据v11单次正常观测及原AI-RESOURCE语义规则，不放宽引用保护、不重写供应方输出、不自动补调用。

## 事件、原因与最终规则

v11技术观测1计数／1Chat，实际输入7309、输出2275、gap3，通过技术准入；原业务progress REJECTED。模型已经使用new_t1—4／new_e1—2，却仍在topic.evidence_refs放消息m1／m2。apply_progress只读重放的根因是Topic evidence is missing，原返回、pending=[2]和零文档状态保留。原五段Prompt已经说明命名，但实际TopicChange字段Schema仍只有宽Ref，字段层面没有表达这条约束。

正式BE完整Schema源的TopicChange.evidence_refs.items增加严格eN／new_eN格式，并在字段旁给出说明及合法数组例子；消息mN只可进入EvidenceChange.source_refs，不是讨论依据。具体引用存在、范围、来源、同轮映射仍由程序验证，不能用格式有效代替授权；无依据可保持原允许的空数组。保持89类型及schema_version=1，不加新根或新HTTP字段。

C07仍分别处理主结果与progress。新字段约束只拒绝非法进度，不否决合法文档／候选，不隐藏原始返回，不建立自动修复路径。没有将m别名猜成e编号。

## 发布与实现

新追加backend/resources/v12，contract及六任务输出资源版本v2，release v4；Prompt仍v3。loader按实际resource_ref取得contract，消除v1文件名硬编码。相对v11只有contract、六输出及release这8项逻辑资源摘要变化；Wire、Canonical、ContextBasis、消息Schema、四阶段、三结构、Prompt及Counting共13项逐字节不变。v9／v10／v11冻结manifest及全部资源文件哈希逐项复核未改。

正式BE SHA256=ab7c7812c6ff730ee4d072c8b52e105b4c2e1792046c3ddaf4d66a2ec85644b6；v12 manifest=3db3a635d5c639d6e1406e717bd7e84d380e70cb4796464fea101477a5810312；release=ad5e45c5e2373ece410d699c886e887c8179ac5303368c6e2fbc668341110a2e。新默认保持OFFLINE_READY，v11原技术凭证不能授给新输出闭包。

## 检查与边界

新增Schema拒绝消息／主题别名、0编号／尾缀／尾换行，合法e与new_e格式通过但不存在引用仍被程序拒绝；补充生成成功同时存在Schema非法进度的实际C07事务路径。完整25文件177 passed／751.61秒（1条既有提示），见offline-suite-2026-10-24-015611-653610.md。实际原v11进度只读重放及纯内存人工对照见progress-reference-schema-offline-2026-10-24.md；该对照不写正常库或冒称模型已修复。

用户明确的第三次单次许可已消耗，未执行v12真实调用或26个真实EV。正常观测库／原失败保留，用户业务数据和服务未动。前端字段与交互未变，未机械重跑前端既有355项／类型／构建证据。

其后仅报告日期及固定准备源码摘要修复，3项CLI／报告／总额度3.38秒通过；26份实际Wire字节／SHA逐项不变，最终准备证据ev-input-preparation-v12-final-2026-10-24.md。没有真实v12调用或EV。
