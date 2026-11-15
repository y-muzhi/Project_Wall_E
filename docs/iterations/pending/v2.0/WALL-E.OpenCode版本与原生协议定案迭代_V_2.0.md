# WALL-E V2.0 OpenCode版本与原生协议定案迭代

日期：2026-11-02（Asia/Hong_Kong）。状态：设计选择已收敛／静态源码核对；未执行协议试验、未实施、未合入正式设计。

## 1. 当前任务与确认

用户要求将两份设计中的未定项“一个个处理”。本轮先处理Q20-OC的版本、原生接口和结果判定，不启动产品或付费验证。

用户另明确确认：接受OpenCode拒绝权限时影响同会话其他待批权限的原生范围；WALL-E按钮统一为“拒绝本会话待批权限”。该确认只决定产品行为，不授权实际拒绝任何运行中请求。

本迭代先保存，再更新V2.0后端0.3-draft-3／前端0.2-draft-2。旧正式设计、原汇总、历史检查和源码保持；本文保留pending，不自动合并或归档。

## 2. 第一项决定

| 项目 | 本轮决定 |
| --- | --- |
| 执行器版本 | OpenCode v1.19.5，锁定发布标签和提交；不使用latest、dev或自动升级 |
| 来源提交 | 810c0eba1a7348036f8bdf61e6632d0c36c6876c |
| 本期分发包 | opencode-windows-x64.zip；当前主机架构只读查询为X64 |
| 包SHA256 | 09a6e693157f0887e504f2cf4357a8cbddc5ead5d0dffb9a269dcc47c48640f5，来自官方发布资产元数据；本轮未下载／解压／运行 |
| OpenAPI | 同提交packages/sdk/openapi.json，Git blob e064da66bda63c78272f398c940755ecf68b0a3f，1063359字节 |
| 调用方式 | Python后端复用HTTPX调用受管原生HTTP，不增加JS SDK依赖；前端仍只调用WALL-E |
| 运行版本检查 | 目标/global/health返回的程序version应为1.19.5；OpenAPI.info.version=1.0.0是规范信息，不能当作程序版本 |
| 其他包／升级 | baseline、ARM64、其他操作系统或版本需独立配置和证据；不能运行失败就静默换包 |

选择依据：[官方v1.19.5发布](https://github.com/anomalyco/opencode/releases/tag/v1.19.5)为当前稳定补丁，发布时间2026-10-28；历史v1.19.4只作测评来源。两标签下OpenAPI的Git blob相同，说明该文件内容相同，不证明所有运行行为相同，历史测评不当作新版本通过。

## 3. 按源码收敛的协议规则

| 条目 | 实际源码事实及设计采用 |
| --- | --- |
| OC20-01 鉴权及目录 | 后端独占loopback原生地址，以实例专用Basic凭据访问；每个实例请求显式绑定实际directory，不依赖默认cwd或把目录交给模型。鉴权不等于OS隔离，后者留Q20-CONFIG／WINDOWS |
| OC20-02 创建会话 | POST /session支持metadata但公开CreateInput不接受客户端指定会话ID。先持久化结构化walle关联及随机nonce，再创建；丢回执按精确元数据／实例／目录关联查原会话，不能靠标题和时间猜，也不重复create |
| OC20-03 投递消息 | prompt_async支持messageID和parts。按锁定Identifier.ascending算法预生成原消息／文本part身份并保存，发送后GET原会话原messageID核对；相同ID不等于原生幂等，未知不重发 |
| OC20-04 原生异步接受 | 204只表示原生接收异步处理。错误可能随后经session.error到达；消息存在、正在处理、业务完成分别记录 |
| OC20-05 状态 | 原生idle／busy／retry与WALL-E任务状态分开；状态Map缺项、idle或abort成功不证明代码／子进程停止 |
| OC20-06 事件 | /event为SSE，JSON数据有事件id；源码不设置SSE的id字段，也没有本入口历史重放保证。不以Last-Event-ID承诺恢复，重连查询原会话／消息／问题／权限 |
| OC20-07 多题答复 | 原生一个question请求可含多题，answers为按原题序的string[][]。后端单一action输入不足，改为逐题index／action／basis_refs，程序组装有依据文本，不让选项自动成为新规则 |
| OC20-08 问题恢复 | 原生pending问题保存在实例内存，reply会移除；列表消失可能是答复、拒绝、取消或实例销毁。200及对应事件是可用正证据；只有消失／404不能证明答复成功 |
| OC20-09 权限影响范围 | 原生once只处理本请求，reject还拒绝同会话其他pending，always扩大后续批准。本期只用once／reject，不用always；用户已确认拒绝范围和文案 |
| OC20-10 停止 | 原生abort仅调用取消过程并返回，完整停止仍核对WALL-E受管工具／子进程／服务，不缩减现有停止保护 |

原生问题／权限的待办是运行态观察，不作为跨实例持久队列。WALL-E仍保存原问题、原答复操作和等待事实；无法证明旧请求实际如何处理时保留未知，不把旧问题重投到新会话。

## 4. 影响范围

- 后端INF-CODE-OPENCODE补精确版本、原生方法／路径、请求／结果和恢复判定。
- QuestionResponse改为answers数组，每题按原index明确选择CITE_FIXED_BASIS或USE_FIXED_BASIS；不新增自由业务规则。
- 权限DENY映射原生reject，但页面表达和实际受影响记录以同会话范围处理；预算／问题／其他任务不会被该动作伪造为已解决。
- 前端问题表单按原请求逐题保留草稿，一次提交整组；拒绝按钮及影响说明同步。
- Q20-OC拆为“设计已定”和“待运行验证”，不继续把已固定的版本和路径列为方案空白，也不提前标协议准入通过。

## 5. 一手来源及已读范围

下列链接固定到同一提交，实际通过官方GitHub连接器读取标签对应文件；大OpenAPI文件超过该读取入口可用大小时改读版本化raw页面，仅阅读本期相关路径／结构，不声称通读全部37012行。

- [发布对应提交](https://github.com/anomalyco/opencode/commit/810c0eba1a7348036f8bdf61e6632d0c36c6876c)与[固定OpenAPI](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/sdk/openapi.json)。
- [会话路由定义](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts)、[会话处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts)。
- [会话对象](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/session.ts)、[消息PromptInput及处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/prompt.ts)、[ID算法](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/id/id.ts)。
- [问题Schema](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/schema/src/v1/question.ts)、[问题处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/question/index.ts)。
- [权限Schema](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/schema/src/v1/permission.ts)、[权限处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/permission/index.ts)。
- [事件输出](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/handlers/event.ts)、[状态Map](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/status.ts)。
- [服务鉴权](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/auth.ts)、[目录路由](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/middleware/workspace-routing.ts)。

## 6. 尚未执行的验证与下一项

本轮未下载／安装／运行OpenCode、未启动实例或模拟服务，未读取业务库，未调用真实模型／计数。包摘要为发布方声明，不冒充本机二进制校验。

协议验收仍需独立隔离试验：版本／鉴权／目录、创建丢回执的精确关联、预分配消息ID核对、重复消息风险、多题／拒绝范围、SSE断线和旧问题消失，以及abort与完整停止分开。模型渠道／Windows／配置等继续按各自条目处理。

本项的设计决定落地后，下一项为Q20-CONFIG：真实配置来源、覆盖、持久存储位置、禁用通道及角色／模型入口绑定。先收敛设计，不自动扩大为运行试验。

本轮静态记录见[版本与协议核对](../../../verification/v2.0/opencode-contract-design-2026-11-02.md)，当前断点见[设计进度](../../../project/v2.0/设计进度_V_2.0.md)。

## 2026-11-09 原问题和权限只读接入

后台按当前原 BACKEND 会话、启动身份、有效授权及工作区归属核对原生待处理列表。问题逐项保存原文、选项及缺省标记，权限仅公开原工具名、模式、动作分类和安全工具引用。持久保存对应等待；传输失败不改原状态，原列表在可信读取中不再出现时保留待核对。API44／45 读现有记录并按原归属、状态和分页投影。后续原答复及权限决定沿 API46／47，权限对象及授权子集须在对应执行门槛核实。

C47 接续核对了固定提交的权限服务及事件流实现。权限服务按原 requestID 处理，并对拒绝实际命中的同会话其他请求逐项发布结果；事件处理器先登记监听，再发连接建立事件，并按实际 directory／workspace 筛选。后续事件端应先确认当前原实例流已就绪，再派发并逐项绑定原权限 ID。现有 JSON 请求在凭据锁内读完整响应，持续事件读取应复用连接与进程身份核验并独立控制取消、期限和关闭。该部分已静态核对，具体响应执行、事件取证及真实实例待接。 [固定权限处理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/permission/index.ts#L99) [固定事件流](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/handlers/event.ts#L22)

## 2026-11-09 原生问题答复接续

API46 固定整组逐题输入、原请求与会话以及程序渲染结果。先查原幂等键，读取固定依据和同任务事实，再在原运行所有者中核对当前原生请求。只有明确接受证据才能解除相应等待；发出后结果未知保留原操作与原问题。工作台沿原问题组件接逐题编辑与原回执恢复。权限决定仍按独立 API47 接续。


API46 实施记录。原连接先尝试就绪有界的实例事件读取，再派发一次固定答复。HTTP 200 且 true 可确认成功；如果 HTTP 回执丢失，只接受同会话、同请求、同完整答复的 `question.replied`。派发意图已持久化但无处理证据时，保留原待核对且不补发。当前执行资源未准入沿既有配置就绪门槛返回 CONFIG_NOT_READY。后续 API47 必须区分单次授权与会话拒绝，实际受影响待批项逐条保存。 [本轮隔离验证](../../../verification/v2.0/coding-question-response-2026-11-09.md)


### 2026-11-09 API47 原权限决定

固定原任务、会话、代次和授权。单次允许先从固定原生工具协议识别工作区内的具体路径，派发时验证原工作区和实际文件身份。无法可靠关联的权限只开放拒绝。拒绝前保存当时可核对的同会话待批项并就绪原事件订阅，按各项精确事件持久化处理事实；缺证项保持待核对。原生 metadata／always 保留在原待批权限的私有观察，原操作只固定相关请求身份。公开详情只返回可核对的对象和结果。工作台沿原回执机制只查询已提交的决定。
