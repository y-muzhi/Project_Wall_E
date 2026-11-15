# V2.0设计

当前代码接续见[实现进度](../../project/v2.0/实现进度_V_2.0.md)和[需求实现映射](../../traceability/v2.0/需求实现映射_V_2.0.md)。以下设计记录保留各自时点；DRAFT、已实现及实际验收分别判定。

- [后端设计草稿](WALL-E.后端设计文档_V_2.0.md)：0.17-draft-17，共同对象、动作、读取／写入契约、存储及外部适配。
- [前端设计草稿](WALL-E.前端设计文档_V_2.0.md)：0.16-draft-16，页面、组件、路由、轮询、草稿／焦点及浏览器存储。
- [架构细化独立迭代](../../iterations/pending/v2.0/WALL-E.代码任务架构细化迭代_V_2.0.md)。
- [前端流程与读取契约迭代](../../iterations/pending/v2.0/WALL-E.前端流程与读取契约细化迭代_V_2.0.md)。
- [OpenCode版本与协议定案迭代](../../iterations/pending/v2.0/WALL-E.OpenCode版本与原生协议定案迭代_V_2.0.md)：v1.19.5及原生映射设计已定，待运行验证。
- [执行器配置隔离与生效迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)：独立配置、实际生效、运行包与变更边界设计已定，待运行验证。
- [Windows受管执行与完整停止迭代](../../iterations/pending/v2.0/WALL-E.Windows受管执行与完整停止迭代_V_2.0.md)：用户已选内置隔离，进程／权限／停止设计已定，待组件与环境验证。
- [设计进度与当前断点](../../project/v2.0/设计进度_V_2.0.md)。
- [后端首稿静态记录](../../verification/v2.0/backend-design-draft-2026-11-02.md)、[前端首稿及契约核对](../../verification/v2.0/frontend-design-draft-2026-11-02.md)。

两份详细规格均为DRAFT；V2.0资料不替代V1.5正式设计，不表示已实施、准入或验收。独立迭代保留pending，正式设计合并需用户明确要求。

早期设计汇总及设计建议记录已不在当前目录，保持删除；当前草稿及接续以两份详细规格和设计断点为准，历史迭代／核对仍保留原时点。

- [OpenCode版本与协议静态记录](../../verification/v2.0/opencode-contract-design-2026-11-02.md)：本轮文档／源码核对，不是协议验收。

- [执行器配置静态记录](../../verification/v2.0/opencode-configuration-design-2026-11-02.md)：本单元核对及未覆盖范围。

- [Windows边界静态记录](../../verification/v2.0/windows-runtime-design-2026-11-02.md)：本单元文档及来源核对，不是隔离运行证据。

- [受控模型协议与预算准入迭代](../../iterations/pending/v2.0/WALL-E.受控模型协议与预算准入迭代_V_2.0.md)：OC20-MODEL-1设计已定／待协议及渠道验证，未实施或发真实请求。
- [模型协议静态记录](../../verification/v2.0/model-contract-design-2026-11-03.md)：来源、契约及保护范围核对，不是渠道验收。

- [完整代码快照与恢复历史迭代](../../iterations/pending/v2.0/WALL-E.完整代码快照与恢复迭代_V_2.0.md)：原工作目录起点封存已由Git版本简化替代；候选／Plan固定包继续按现行草稿，历史运行证据状态不提升。
- [代码快照静态记录](../../verification/v2.0/content-store-design-2026-11-03.md)：本单元结构、契约及保护范围，不是文件／Git恢复证据。

- [Git交付协议与并发恢复迭代](../../iterations/pending/v2.0/WALL-E.Git交付协议与并发恢复迭代_V_2.0.md)：GIT20-LOCAL-1设计已定，固定工具／引用事务／窗口及恢复尚待运行验证，未安装或操作用户分支。
- [Git交付静态记录](../../verification/v2.0/git-delivery-design-2026-11-03.md)：本单元契约与保护范围，不是Git运行证据。

- [独立检查资源与结果准入迭代](../../iterations/pending/v2.0/WALL-E.独立检查资源与结果准入迭代_V_2.0.md)：CHECK20-CONTROL-1设计已定，受控资源／driver／真实边界未发布或验证；不以项目自报代替功能验收。
- [独立检查静态记录](../../verification/v2.0/check-resources-design-2026-11-03.md)：本单元契约、范围及保护摘要，不是检查运行结果。

- [数据库保留升级与恢复迭代](../../iterations/pending/v2.0/WALL-E.数据库保留升级与恢复迭代_V_2.0.md)：DB20-UPGRADE-1设计已定；备份演练、原库事务／恢复及保留规则已同步DRAFT，未生成SQL或操作数据。
- [数据库升级静态记录](../../verification/v2.0/database-upgrade-design-2026-11-03.md)：本单元契约与保护核对，不是迁移／恢复证据。

八项技术设计已有明确结论，实际资源、代码、隔离升级和运行证据仍待后续任务；两份草稿继续DRAFT。

- [详细规格模板校正迭代](../../iterations/pending/v2.0/WALL-E.详细规格模板校正迭代_V_2.0.md)：按项目模板逐对象／能力／入口／页面／组件及AI评测展开，保留八项技术选择和DRAFT状态。
- [模板符合性静态记录](../../verification/v2.0/template-conformance-2026-11-03.md)：本轮具体核对范围及结果，不是实现或产品验收。

- [字段、阶段与命令恢复契约修复迭代](../../iterations/pending/v2.0/WALL-E.字段阶段与命令恢复契约修复迭代_V_2.0.md)：五项设计问题全部修复，新增事实澄清与IDB原命令恢复，仍DRAFT／待实施验证。
- [五项修复静态记录](../../verification/v2.0/design-contract-fixes-2026-11-03.md)：字段／存储、阶段门槛、答复分支、持久事务及新增验收目标核对；不是产品或运行验收。

- [Coding与Testing独立模块迭代](../../iterations/pending/v2.0/WALL-E.Coding与Testing独立模块迭代_V_2.0.md)：用户已确认职责拆分，两份草稿已同步独立任务、计划／资源、报告与缺陷复测。
- [独立模块静态核对](../../verification/v2.0/coding-testing-split-2026-11-03.md)：本轮范围与证据，仍DRAFT／待实施验证。历史测试专项挂CodeTask执行的说明不再作为现行职责，构建评测／自迭代仍独立pending。

- [交叉审阅与原命令关闭修复迭代](../../iterations/pending/v2.0/WALL-E.交叉审阅与原命令关闭修复迭代_V_2.0.md)：2026-11-04，六项评审问题已同步两份DRAFT，补齐批次依赖、原键关闭、费用舍入、负余额、原观察读取及部分／最终用量契约。
- [完整交叉审阅修复核对](../../verification/v2.0/full-design-review-fixes-2026-11-04.md)：新增20项验收目标，结构／引用及8项精确金额静态核对通过，未实施或运行验证；[原评审](../../verification/v2.0/full-design-review-2026-11-03.md)保持历史字节。

- [11月4日完整评审](../../verification/v2.0/full-design-review-2026-11-04.md)及[修复迭代](../../iterations/pending/v2.0/WALL-E.11月4日完整评审修复迭代_V_2.0.md)：自然收尾、Testing状态／接口、路由／分页及产品边界已同步两份DRAFT；[静态核对记录](../../verification/v2.0/design-review-1104-fixes-2026-11-04.md)列实际范围与待实施验证事项。

- [未启动任务终止修复迭代](../../iterations/pending/v2.0/WALL-E.未启动任务终止契约修复迭代_V_2.0.md)：两模块原终止支持可靠空执行范围证据；[静态核对](../../verification/v2.0/unstarted-task-termination-design-2026-11-04.md)记录派发屏障、资源收尾和待实施验证边界。

- [已提交Git版本起点简化迭代](../../iterations/pending/v2.0/WALL-E.已提交Git版本起点简化迭代_V_2.0.md)：起点改为固定commit登记，不另封存代码包；[静态核对](../../verification/v2.0/git-baseline-design-2026-11-04.md)记录版本保留、来源可用性、读取与待实施边界。

- [Git历史读取与当前内容校验实施细化](../../iterations/pending/v2.0/WALL-E.Git历史读取与当前内容校验实施细化_V_2.0.md)：历史与当前内容边界、原观察API71及既有状态实现偏差修复；实施证据见现行需求映射，继续pending，未合并正式设计。
