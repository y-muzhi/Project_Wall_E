# WALL-E V2.0 11月4日评审修复静态核对

日期：2026-11-04（Asia/Hong_Kong）。来源：[11月4日完整设计评审](full-design-review-2026-11-04.md)。结果：RV20-01—07及三项补充边界均已修订；用户已确认两项产品范围。两份继续DRAFT，未实施或取得产品运行证据。

## 1. 基线、修改及授权

接续后端0.14-draft-14／前端0.13-draft-13，与原评审列出的SHA256一致。先保存[独立迭代](../../iterations/pending/v2.0/WALL-E.11月4日完整评审修复迭代_V_2.0.md)，再按原章节职责同步为后端0.15-draft-15／前端0.14-draft-14。

本轮修改7份V2 Markdown：两份草稿、独立迭代、两个索引、设计断点和本记录。原评审、11月3日评审修复证据及其他历史资料保留原字节；不合并V1.5正式设计或原V2汇总，不改产品源码／SQL／配置／资源／数据，不启停服务、执行产品／浏览器／真实模型／计数、安装、提交或推送。

## 2. 逐项修订

| 条目 | 现行设计及关键边界 | 核对结论 |
| --- | --- | --- |
| RV20-01 正常完成收尾 | SHR-CODE-FINALIZE：原DELIVER增加FINALIZE_OWNED_RUNTIME，封闭代次／模型入口，退役会话，核实全部历史代次及迟到启动、Job／工具／服务和原Git结果，再撤销凭据及回收本owner WFP／LPAC等资源。保存STOP和新增CLEANUP观察及原步骤引用；不伪造用户TERMINATE | 交付／postcheck成功仍不足以COMPLETED；收尾失败或未知WAITING／DELIVERY并保留名额，已交付事实不回滚／不重发。重启或停止抢占仍用原身份。状态、存储、运行时读取、Guard、Git和前端同步；真实Windows／释放恢复未执行 |
| RV20-02 Testing终态终止 | APP-TEST-TASK、BND-TEST-API-31和客户端：首次及STOPPING202原TestingReceipt，COMPLETED／TERMINATED200 TASK_ALREADY_ENDED语义的TestingTaskView | 自然完成可合法termination_operation_id=null，不造停止操作；原回执重放取首次HTTP及结构，后来的终态不重算原202。联合decoder是设计目标，未运行 |
| RV20-03 Testing状态迁移 | SHR-TEST-READINESS统一CREATE／ATTACH绑定和同事务持久就绪判断；齐备创建READY，否则DRAFT。同资产新键显式重验、原版本CAS，无变化不增版；已绑定不换版 | 补8态逐动作矩阵、内部PACK_VALIDATION差异、资源失效事件、无原操作的执行前重验和有原操作的WAITING恢复。GET不写状态，原拒绝沿既有无业务写入规则，已派发未知步骤不重放；真实状态／事务未执行 |
| RV20-04 Testing错误集合 | SHR-TEST-ERROR明确自动适用公共边界＋45个入口各自专有集合；创建、预算、执行等逐入口列403 AUTHORIZATION_NOT_APPLICABLE | 原403和AuthorizationDetails不吞为500；TERMINATE／RECONCILE不依赖执行授权、runner、模型或预算就绪。原拒绝回执使用同入口decoder，静态逐入口核对通过 |
| RV20-05 六页签及接收身份 | Coding统一execution／code／checks／testing／delivery／usage，URL／history／TaskLocation含明确test_report_id及各页位置；交付组件只绑定candidate／test_report／plan／目标旧值 | 删除五页签与verification接收身份残留；报告选择复用testing-tasks的candidate_id过滤与report_id读取，不新增列表API。深链及页面未实际执行 |
| RV20-06 全局入口 | “代码开发”固定复用/requirements工作台，再明确选择需求／文档进入文档code-tasks；受控history.nav_intent=CHOOSE_CODE_DOCUMENT只作导航提示 | 无上下文、空列表、历史实体失效及后退均有确定行为，不猜最近任务，不新增汇总页、服务或写操作 |
| RV20-07 分页结构 | Coding／Testing统一page1—100000、固定20，Query不接收page_size。Page<T>只是公共data.items及meta.pagination的文档简称 | 明确内部APP分页经原http_projection拆分；空总数total_pages=0，越界保留真实总数及所请求page，不嵌套Page对象。4个总数算术向量通过，真实投影及decoder未执行 |
| RV20-R1 新项目冷启动 | 用户选择首期预登记参考项目；新项目可保存任务／计划草稿及准备资源，未登记参考集时不接受包验证／发布或PRODUCT执行 | 部署维护者在产品外准备并审阅真实参考／缺陷集，本期无产品内准备审核工作流；不拿候选自证，不以DIAGNOSTIC绕过验证。ready=false及REFERENCE_SET_NOT_REGISTERED／Q20-CHECKS有明确映射 |
| RV20-R2 发布后换配置 | CheckSet／runner／必要环境变化时，应用新配置事务保留原候选发布及交接，清空当前报告／Plan并回VERIFYING；明确同候选重新自检 | 当前三阶段自检不再适用时禁止先关联旧报告绕过重查；合格后回AWAITING_TESTING，旧独立报告仍适用时可重新关联，否则新Testing，再新Plan／接收；无需先造缺陷REPAIR |
| RV20-R3 人工覆盖 | 用户选择接收时接受尚未自动验证范围的剩余风险；新增Acceptance.manual_risk_accepted及相同AcceptCode输入、字段表／200映射 | 原报告人工范围非空须true、为空false，确认默认false、变更身份或重开重置；不造逐项人工PASS或宣称全部验证。自动必检失败及UNCOVERED仍禁止交付 |

本轮未把运行证据缺失重复判为新设计错误。Q20各项ready=false和后续真实证据边界继续保留，不因以上修订宣称协议／环境组合已实际可用。

## 3. 实际静态检查

使用rg检查原问题词句、状态／动作、接口和引用；内存Python检查Markdown字段／表格／围栏／相对链接、OBJ／APP引用、全部直接对象成员、API／客户端路径、45项Testing错误集合、终止成功分支、旧规则残留及目标场景唯一性。脚本仅经PowerShell管道在内存执行，不留脚本、JSON报告、截图或日志。使用git status --short、git rev-parse HEAD、git diff --check只读核对现场。

结果：

- 两份均保持模板八章、16个对象、20个能力；524行字段、42组记录；116个接口，其中45个Testing入口已逐项整理错误。直接对象成员、OBJ／APP引用及本轮提取的客户端路径无缺定义／未映射项。
- 7份本轮文档的本地Markdown链接可解析，表格列数、围栏、空白、版本和唯一当前断点核对通过。外部链接未重新联网验证。
- 新增后端TC-RV20-01—12、前端TC-FE-RV20-01—10，共22项验收目标；后端累计148项、前端103项。本轮产品场景执行0，4项EV继续为未执行计划。
- 按固定20分页精确核对total为0／1／20／21，对应total_pages为0／1／1／2，通过。此为设计算术核对，未导入或执行产品函数；页范围、未知page_size和响应结构仅静态检查，不能冒充HTTP／浏览器验证。
- 48份保护文档及283份backend/app／frontend/src源码文件摘要与本轮开始一致。V1.5及其他任务既有工作区改动保留，未回滚、覆盖或当作本轮成果。
- HEAD保持8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，git diff --check通过，本轮原子保存临时文件0。

| 草稿 | 接续SHA256 | 收口版本／SHA256 |
| --- | --- | --- |
| 后端 | faf29ff8a240fd17c4c86a90cc07a4a036171e4e00eb0312562993e2f034ccd2 | 0.15-draft-15／aecdebc70a0be9ffe3b28cc4e659e36a6a53cedb5acce05f428cae262e4358d4 |
| 前端 | 0c5563558cd843fd222fd9b2028a55c67ca1c6d6f862cde0ac355200529991a7 | 0.14-draft-14／3186284219579475b3c0e321be408ce133057c449f63b269bd414790396b96c8 |

## 4. 未实施及接续

真实FINALIZE步骤／Guard释放和迟到启动恢复、200 Schema及manual_risk_accepted／CLEANUP约束、Testing应用矩阵／HTTP注册、严格联合decoder、六页签／history、人工确认及参考资源均尚未实施或实际验证。后续实施仍须按两份第8章与附录A取得Windows、原生协议、Git、模型、检查资源和数据库保留升级的真实证据；本轮没有新增真实调用许可。

没有本轮产品进程、数据库、资源安装或源码半成品。当前完整断点见[设计进度](../../project/v2.0/设计进度_V_2.0.md)；独立迭代留pending，设计定版、代码实施和软件验收分别处理。
