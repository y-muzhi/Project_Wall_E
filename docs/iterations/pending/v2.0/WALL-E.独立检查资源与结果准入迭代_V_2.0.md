# WALL-E V2.0 独立检查资源与结果准入迭代

日期：2026-11-03（Asia/Hong_Kong）；编号M20-CHECKS-01；对应Q20-CHECKS；状态：设计已定／待资源发布与真实检查边界验证。保留pending，具体共同契约归后端，页面归前端，不形成第三份正式规格。

## 1. 任务与边界

按用户“继续完成任务”接续第七项。起点后端0.8-draft-8／前端0.7-draft-7，均DRAFT；前六项及用户确认保持。本单元只写V2.0 Markdown、静态阅读现有代码／依赖锁和官方资料，不改产品代码、资源、用户正文／配置／数据，不安装依赖或浏览器，不运行检查／服务／浏览器／模型／计数，不做系统或Git写入／提交推送。

缺少真正运行资源不能写成已经可用。本项定案是资源格式、独立断言、环境与结果准入机制；资源及项目专用用例在后续实施／准备批次发布，本轮不生成占位包、不编造资源ID或通过证据。

## 2. 现有能力与真实缺口

- tools/check-v15-offline.py调用quality_gate，现有七阶段、依赖先安装、临时输出／Markdown记录、源码摘要及取消规则可作复用来源；它固定WALL-E目录／脚本，不是通用项目验收服务。
- 其Python审计钩子／Node连接拦截和taskkill为该工具已实现规则，不能当V2.0的LPAC、Job或对任意用户代码的安全证明。PROJECT_COMMAND执行候选测试／构建／插件属于运行不可信代码。
- 当前frontend/package.json／lock及backend requirements.lock／requirements-dev.lock可证明本项目声明版本；不自动成为所有目标项目依赖、已取得浏览器包或已准入runner。
- run-v15-evaluation含真实模型／计数入口及明确次数预算，不进入本期默认检查，不复用历史调用许可。
- 旧EXIT_CODE_AND_MARKERS不足以证明独立断言：项目可以改脚本、打印PASSED或提前退出0。不能把此路径包装成独立业务验收。

## 3. 采用CHECK20-CONTROL-1

### 3.1 检查类型与阶段

延用CheckSetVersion／CheckDefinition／Verification，不新建评测平台。协议不把目标绑定到WALL-E技术栈；每个项目按固定Revision和已登记工具发布自己的检查／用例资源，具体栈没有资源就不可用。

两类检查：
- PROJECT_COMMAND：候选内的测试、格式、类型、编译及其配置／插件都视为项目代码；只记录原命令、真实退出、来源版本和隔离事实。正常退出只代表这一命令完成，不能替代独立功能验收。
- CONTROLLED_ASSERTION：受控程序核对固定内容完整性，或以CLI／HTTP／BROWSER方式观察候选行为，与外部固定预期比较；检查器及预期不由候选动态加载、修改或自报。

删除当前DRAFT中EXIT_CODE_AND_MARKERS作为权威结果的分支，不保留第二套兼容判断。evidence_rule.kind取PROCESS_EXIT／CONTROLLED_CASES／CONTENT_INTEGRITY。每个适用阶段至少有必检完整性项和非空的受控功能用例；只有项目命令通过的CheckSet不可用于自动交接／接收。

HANDOFF选择当前角色和已完成角色的必检并去重；ACCEPTANCE再加ACCEPTANCE项，覆盖最终整体。固定scope_stages与selected_check_ids，不随执行中配置／候选变动重算。首期不跨候选缓存，复用仅同候选／配置／目的／角色／范围与必要环境，记录reused_from_item_id，不能冒充新执行。

### 3.2 受控资源与覆盖范围

RunnerBundleManifest固定protocol、入口／解释器／浏览器／依赖、全部文件摘要、能力和环境证据。CasePackManifest固定用例、步骤／字面断言、来源Revision及覆盖计划。两者在可写代码根外，由登记资源目录提供，不由模型输出或用户任意路径／脚本充当资源。

固定case覆盖按AUTO／MANUAL／NOT_APPLICABLE登记来源引用、适用阶段、check_ids及说明。AUTO必须实际映射相应受控功能项；MANUAL在人工接收时明示，不伪装自动验证，不另强迫逐项点击。程序能核对引用与资源一致性，不能自动证明自然语言验收覆盖完整；发布前需按固定设计审阅。没有用例或必要人工范围未说明时不发布可执行配置。

首期资源能力为CONTENT_INTEGRITY、CLI、HTTP、BROWSER；它们是设计目标，不是已发布包。已有WALL-E质量脚本仅作为PROJECT_COMMAND参考，不能列为现成跨项目受控功能资源。Codex提供的浏览器／测试工具也不当作WALL-E产品依赖。

### 3.3 执行、身份及隔离

每项使用独占检查副本与假数据，原候选包不改。产品输入路径只读，写入只限声明的非产品输出／临时／测试数据库；输出目录与产品条目不得相交。编译必须生成产品源码时，应先在编码阶段形成新候选，检查不能放宽源权限、自动采用副本修改或把测试改稿合回工作区。

项目命令及被测应用按TASK／LPAC运行。可信CLI／HTTP断言由既有后端受控解释器执行，不import／eval候选代码或读取候选conftest／Playwright配置；它启动的被测程序仍是TASK。浏览器驱动新增CHECK_DRIVER：独立LPAC身份、受控只读入口／用例、独立Job与私有I/O；不得Node-import候选模块或把项目测试目录当检查器。两种身份不能写彼此资源或共享结果管道，模型入口拒绝CHECK_DRIVER。

浏览器只用固定包、全新profile，保持chromiumSandbox=true，不降级--no-sandbox／关闭web安全。不附着用户浏览器、不复用现有服务；无法满足Windows／浏览器／Job组合就UNAVAILABLE。此为Guard run_kind及资源清单补充，未安装或实现，不改前项历史迭代。

测试端点是本次被测Job的私有映射，不能传任意URL或借固定8000／5173用户服务。连接发送业务字节前证明归属本次应用Job；端口占用／复用／无法证明直接UNAVAILABLE，不能仅凭HTTP200认领。服务命令和端口由已批准模板绑定；CLI输入输出也只绑定原CommandExecution。

网络默认只通本轮受管测试端点及受控离线替身；重定向、WS、worker／子资源及浏览器出站均受边界约束。检查不取供应商密钥／真实业务秘密、不发真实模型／计数或外部服务调用；即使任务另有广泛网络许可也不扩大检查。受控替身只证明相应离线行为，不冒充真实渠道兼容。

依赖／浏览器必须预准备且匹配候选锁；缺失UNAVAILABLE，不隐式npm ci／pip install／npx下载。明确获准的环境准备走原配置／命令与授权，之后新建EnvironmentRecord，不借“检查”安装工具或改用户服务。

### 3.4 用例、权威结果与重试

CasePack只允许有界的字面操作与预期：CLI stdin／exit／stdout、HTTP方法／相对路径／状态／头／JSON值、浏览器受控定位／点击／输入／可见性／文本／数量。无eval、任意JS／Python、正则程序、动态插件或自报“pass”。每例至少一个断言，完整执行指定用例／步骤且无skip／缺项才可能通过；超时及输出／载荷超限不缩减预期集合。

受控结果从后端断言逻辑，或绑定CHECK_DRIVER根进程的专属继承管道取得；浏览器／被测子进程不继承该写端，项目stdout不按权威协议解析。帧绑定原verification/item/nonce／资源／case序号，程序验证实际根身份、单调序号、case集合和正常结束，缺终帧不补造通过。令牌／nonce本身不是唯一身份保证。

CLI／HTTP／browser的实际观察与固定预期比较，PASSED为可信检查器得出的结果，不读取候选生成的JUnit／JSON／TAP为独立判定。PROJECT_COMMAND真实退出与诊断保留，stdout计数仅标项目自报，空测试不能替代功能项。Python pytest无测试的非零退出不改成通过。

本期同任务串行检查、每例无自动重试、无模型裁判和自动AI修复；显式重新检查形成新Verification，旧未知先核清所属活动，不能改写旧通过或启动重叠服务。

### 3.5 结果、恢复与清理

VerificationItem记录check_kind／evidence_kind、expected／executed／passed／failed用例数（项目命令为null）、reused_from_item_id和实际环境。受控case事实追加保存为子记录，新增同任务／检查／Item归属的只读分页用例入口（每页20），摘要不塞入TaskView或所有Item轮询；原正常业务审计保留；不把临时JUnit／截图／trace／HAR等留存为第二套证据。

项目／驱动退出0不够：必须完整用例结果、所需断言、资源／候选／环境不变、所有所属Job／应用服务停止、输入完整性核验及清理已证实。assertion失败为FAILED，资源／隔离／端点缺能力为UNAVAILABLE，活动／结果／帧冲突无法核清为UNKNOWN；取消保留已保存的已完成用例事实，不把未执行项补通过。非零不自动当业务缺陷。

每项后停相关Job、核对只读输入，再清理本轮独占临时；清理／停止未知时保留已有断言事实但eligible=false，不将其改成绿色整体验收。只删除已核实归属的绝对受管临时路径，引用的候选、资源、业务审计与用户数据不动。进程未知不先清目录；恢复只核对原步骤，不重跑HTTP写动作或重建应用。

原APP-CODE-VERIFY“检查修改源后形成新候选”收敛为明确失败／不采用；有意产品代码生成回到编码及重新捕获。旧Item／Case记录不可因重试、依赖更新或新配置覆写。若已可靠核清原活动停止及私有测试数据／目录收尾，但完整结果永久缺失，原Item／Verification保留UNKNOWN；原检查操作可因EVIDENCE_INCOMPLETE明确失败结束，用户显式新检查才建立新Verification。活动／清理尚未知时不可这样释放占用；迟到只补原历史，不覆盖新检查或恢复执行。

## 4. 契约与未完成资源

计划更新后端0.9-draft-9／前端0.8-draft-8，均DRAFT；新增CasePack／RunnerManifest受控目录投影、check_kind／目标／覆盖与证据规则、CHECK_DRIVER绑定、Verification范围与汇总／子记录、停止／清理及未就绪原因。沿既有设置／检查／RESUME与只读入口，不增加任意脚本、客户端判通过或自动安装接口。

资源准备顺序：发布受控controller／driver和依赖包 → 真实Windows隔离／端点／管道／故障自检 → 为固定设计发布casepack及覆盖 → 发布可采用CheckSetVersion。任一步缺失只保DRAFT／ready=false，不伪造路径、Schema、编号、fixture或运行证据。本轮不创建实际资源文件。

追加TC20-77—84及TC-FE20-50—52，仅为未来目标，执行0。Q20-CHECKS设计已定／待资源发布及真实边界验证，不把“选了检查器名称”当实际检查可运行。

## 5. 来源与阅读范围

读取日期2026-11-03。本地已读quality_gate／quality_python／quality_node和其8项自检源码、check-v15-offline入口、当前包与依赖锁、run-v15-evaluation明确真实调用边界及相关分支；未运行这些工具。第一次误定位前端BND-CODE-VERIFY，已改读实际BND-CODE-CHECKS，不虚构组件。

官方[pytest退出码](https://docs.pytest.org/en/stable/reference/exit-codes.html)用于区分无测试／错误；[npm ignore-scripts](https://docs.npmjs.com/cli/v11/commands/npm-ci/)不阻止明确npm test／run本身执行，不能当隔离。
[Playwright BrowserType](https://playwright.dev/docs/api/class-browsertype)用于核对浏览器沙箱选项；[webServer](https://playwright.dev/docs/test-webserver)用于避免复用已有服务及把就绪HTTP状态当归属证明；[Python隔离模式](https://docs.python.org/3.13/using/cmdline.html)及[Node环境](https://nodejs.org/api/cli.html)仅作受控启动参考，不替代OS权限。

以上相关段落及现有依赖版本只作设计依据，未通读全部测试框架／浏览器／OS实现，也不把当前项目锁文件或当前Codex环境登记为已发布产品runner。覆盖判断和本次分层方案为设计推导，不是官方工具自动提供的全链保证。

## 6. 验证与接续

静态记录见[独立检查设计核对](../../../verification/v2.0/check-resources-design-2026-11-03.md)。未执行产品检查、浏览器、网络／端点、OS／Job、依赖安装、模型或计数；真实资源与准入仍未完成。

下一项Q20-DB：沿现有SQLite Schema校验及迁移机制设计V2.0保留升级、备份、事务／校验与中断恢复。只设计方案，不操作正常业务数据库。

## 7. 实施细化（2026-11-10，私有离线项目命令）

公开 CheckSet、Verification、Coding 与 Testing 的规则沿正式两份设计。首个执行分支限定原 CODING 项目 CHECK、已登记固定可执行文件和无网络命令。实际子进程仍是 TASK／LPAC，工作区为原封存候选独立副本，scratch／output 可写。项目命令采用固定参数数组，只有完整 CHECK_INPUT／CHECK_OUTPUT 参数可替换为本轮目录；无继承个人环境、模型配置或模型源资格。原执行记录绑定 owner／generation／verification／item／candidate／manifest 摘要和实际命令定义，原 WFP 安装意图及六个阻断规则须读回后才允许创建／恢复。既有 OpenCode 分支仍用原端点和运行环境。

私有文件传递以原认证控制进程的只读句柄绑定启动步骤。WALLECK1 内容为固定小端头、原规范清单及按清单顺序的原文件字节。Guard 核对确切来源、原句柄、总长和摘要，逐文件检查，完整接收后才返回 PREPARE。后端未收到原确认时保留原传输文件待核对。项目输出只用于项目命令事实，后续项目结果仍需原实际退出、停止、输入复查及清理。CLI／HTTP／BROWSER 独立受控用例、CHECK_DRIVER 以及正式安装资源不由本段代替。


首个后台分支复用原 CAPTURE_AND_CHECK 的 CHECK 步骤，先同事务固定原环境、检查项、命令和原 START 配置关联，再记认证动作意图和回执。已开始的范围即使失去结果也保留原身份，STOP 和 RELEASE 只针对原 scope。读 API 只公开结果摘要及必要环境，控制身份、原句柄和原输出不随响应返回。当前限定已接受的单 BACKEND 捕获及单个登记项目命令，后续需要补原未知范围核对、其余阶段、受控用例及前端操作。 [实施验证](../../../verification/v2.0/coding-project-check-2026-11-10.md)


## 8. 实施细化（2026-11-10，固定用例包与只读结果）

私有 CasePack 的步骤和断言使用严格对象及单例操作词，不扩展 HTTP 输入。CLI 步骤固定 RUN，带已登记 command_id 和标准 Base64 stdin；断言固定 EXIT_CODE 或 STDOUT_BYTES，比较原生退出码或字节。HTTP 步骤固定 REQUEST，带 endpoint_ref、相对请求路径、允许的方法、请求头和标准 Base64 body；断言引用原 step_id，按 STATUS、HEADER、BODY_BYTES 或 JSON_POINTER 固定比较。BROWSER 使用 NAVIGATE、CLICK、FILL、SELECT、PRESS 步骤，以及 VISIBLE、TEXT、COUNT 断言；定位器固定为 TEST_ID 或 ROLE（可精确附名称）。不接受未知键、未声明命令或端点、任意程序、外部地址、重复 ID、未引用的 HTTP 步骤或无断言用例。JSON Pointer 只承载有界数据寻址，字面比较保留 JSON 类型。资源内所有步骤、断言及用例必须符合固定配置上限，浏览器、HTTP 和 CLI 执行器按各自实际准入接入，解析通过不发布资源。

资源读取以受管目录身份、固定 Manifest 摘要与包 ID／版本绑定。EnvironmentRecord.check_resource_refs 中以 casepack:sha256:<摘要> 记录原固定字节身份，原 CheckSetVersion 内的 case_pack_ref 保持正式引用。原结果读取须同时匹配两者。历史可保留原摘要资源；缺原摘要返回 CONFIG_NOT_READY，当前目录中的同名新包不能替换旧包。API55 同一 SQLite 快照绑定 Coding task／Verification／Item 及原 CheckSetVersion。项目命令和完整性项的合法查询返回空页。受控项只投影原已保存 Case 记录，实际值留在私有记录，公开摘要由结构化结果生成。按 case_id 稳定排序，使用原已记录数分页。没有 Case 记录时保留真实空页。


## 9. 固定候选内容读取的实施细化（2026-11-10）

候选差异沿 BE API29／56／57 和 FE BND-CODE-CONTENT。BEFORE 只读候选所指原登记快照及已保留 Git 对象，AFTER 只读候选自身封存包，不以 parent_candidate_id 或工作区替换。DiffItem 精确按 UTF-8 路径排序，不做改名推断。仅模式不同为 MODE，内容变化为 MODIFY；任一存在侧含 NUL 或无法严格解码 UTF-8 时标二进制。读取比较侧时验证该路径属于原差异；一侧不存在返回 exists=false，保留真实空文件与分块末端的区别。原包和基线均按原检查／秘密策略及真实身份复核，浏览器按需增量读取，任何读失败单独显示。工作台测试和部署证据分别记录。


## 10. Coding 角色链实施细化（2026-11-10）

顺序交接为 APP-CODE-HANDOFF 内部工作流；原公开自检仍只接受 HANDOFF 目的，浏览器不发送角色交接。角色链读取核对同任务原 HANDOFF_ROLE 的固定来源会话、候选、检查、目标角色及原状态版本。QUIESCE 引用同代次原已核实的停止写入观察，REVOKE 保存退役会话和新控制代次，CHECK 引用固定原检查，CREATE_SESSION 保存唯一目标会话及实际原生会话身份，SEND_HANDOFF 保存该目标的实际首次原生消息身份。五步均成功且同任务／角色／代次／候选一致才计入前缀，未知或残缺不计入。原检查必须具有真实同任务的范围、必要项、输入及收尾证据；后续资源变动影响当前资格，原已经成功的交接历史保持。现有原 START 宿主凭据和 Guard 启动身份不会因业务代次前进而改写，新原生动作以独立交接操作身份保存；新会话须取得原消息确认及唯一写入资格后才进入下一角色。


## 11. Coding 候选发布的实施细化（2026-11-10）

APP-CODE-PUBLISH 使用设计 API68 和原幂等回执。用户显式选择当前联调候选与实际 HANDOFF Verification。后台复核同候选三阶段、两次已确认的原角色交接、现行配置和独立检查资源、真实输入与收尾，以及全部原写入和未决问题。VALIDATE 保存这些原引用，SAVE_FACT 仅保存同一候选的原发布事实并进入待独立测试。公开成功仅为设计定义的 UPDATED，独立 Testing 保持另外的显式任务入口。工作台从原发布和真实阶段显示状态；无法核实的环境、包或原链分别保留阻塞原因。


## 12. 原交接投递的显式核对（2026-11-10）

API38 的首个角色分支仅核对原 HANDOFF_ROLE 的 SEND_HANDOFF。请求固定同任务原操作及版本，后台新建只承担 QUERY／COMPARE／RECORD 的核对记录。观察只读原已保存 native intent 和同一实例的已接收消息，必须匹配原新会话、消息及受信旧运行所有者。确认后补写原交接并在原运行入口仍可核实时恢复唯一新会话；观察不到时记录仍待核对并保留原等待。查询不会创建会话、投递消息或产生新检查。CREATE_SESSION 等其他原范围待分别接入对应恢复证据。

## 13. Testing 私有原生项目检查（2026-11-10）

Testing 离线被测命令使用私有 WIN20-TESTING-CHECK-1，保留 TASK／LPAC。原操作请求及私有凭据覆盖 Testing owner、任务 ID、操作 ID、控制代次、步骤、nonce 和原控制方。旧协议、其他任务和代次不能观察或关闭原 Testing 项目检查。Testing 只匹配明确标明本 owner 类型的部署准入，不能借用 Coding 准入或进入模型来源路径。已有 Coding 范围格式保持兼容。

该原生路径提供私有退出、输入完整性和清理事实，后端 CLI／HTTP 断言及浏览器 CHECK_DRIVER 仍分别使用 3.3—3.5 的权威结果规则。 [隔离 Windows 专项](../../../verification/v2.0/testing-guard-owner-2026-11-10.md)

## 14. 独立 Testing 的后端断言与服务边界（2026-11-10）

第一批执行将已登记 CLI 与单个受控 SERVICE 接同一原 RUN_TEST。CLI 可从原后端经有界管道发送固定标准输入，完成全部发送并核对原退出、停止、输入及清理后才比较。HTTP 固定一个登记 IPv4 回环端点及服务根，每步只新建一条经 Windows 原监听和双向连接归属核实的连接。原 Guard 同时核对原 Job、根身份、启动回执及未关闭栅栏。请求首字节前保存同任务原步骤意图，后台不跟随重定向，不能通过代理、正常服务或其他端点回退。请求结果未知时只核对原步骤并收尾，不能重放 HTTP 写入。

私有结果仅留固定步骤引用、脱敏断言及收尾证明。服务为验证结束而正常受控终止时保留真实退出码，HTTP 断言依据原响应和已核验收尾。首批仅接受单服务和无外部依赖。空夹具沿原路径，非空夹具由可信安装按固定摘要登记和逐文件核对，在独立 basis 只读树中与被测候选分开授权、复验和收尾。独立浏览器、复合应用链与正式 SYSTEM／WFP 部署仍分别准入。


## 15. Testing AI 起草与 Coding 缺陷登记的实施细化（2026-11-10）

API26 按明示配置启用一次独立 Testing 模型起草。请求上下文只含任务固定版本与材料、已核对的能力及输出契约。原任务版本、预算和授权由后端在原范围复核。只保存一份独立 DRAFT，后续资产绑定、计划发布及运行继续依照各自显式动作。未知发送或费用仅核对原记录。迟到用量仍可结算，原任务停止后禁止采纳迟到草稿。

API58 人工分支只接收固定原文和同任务 EvidenceRef。导入分支要求同固定设计、材料及当前候选的原 PRODUCT Finding，保存其实际行为、预期、依据和唯一来源引用；后续原 Finding 的归因变化不改写已存缺陷。两分支同一事务登记，修复需另行明确发起。

## 16. CHECK_DRIVER 与双端隔离转发（2026-11-10）

固定浏览器运行闭包与候选隔离。驱动只接收从原封存包切出的单用例和只读数据声明，独立 Job 中禁止模型和直连网络。原根进程在载入浏览器工具前撤销结果写端继承，结果仅经专属有界管道，经原 nonce／帧序列／退出码／清理复核。Chrome 通过两端独立受管 TASK 的原端点取得实际页面与响应。后端首字节前记录原请求摘要，按 TCP 双端身份与原 Guard Job 验证，不重放可能已发请求。单 origin 的不同路径可明确匹配前端与后端，响应按受控规则保留安全头。当前联通准入范围为两端和固定 HTTP；未准入的跳转、Cookie、跨源、WebSocket 和 Service Worker 关闭或拒绝。正式接收只认同一用例两端均有原通信及三者收尾证据。 [专项记录](../../../verification/v2.0/testing-browser-driver-2026-11-10.md)
