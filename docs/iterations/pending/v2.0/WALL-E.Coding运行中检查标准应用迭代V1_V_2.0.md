# Coding运行中检查标准应用 V1

2026-11-11，依据BE 0.17-draft-17（SHA256 1A8D277F25DE570CE72E74A73FF763BF73F622FCF94B61F0820B78A1A5C6FD37）的APP-CODE-CONDITIONS、OBJ-CODE-POLICY／VERIFICATION、SHR-CODE-VERIFY-STAGE及7.6，FE 0.16-draft-16（SHA256 38557CEE854697044AB7DABA30F694738429BE1235264A153851E8FC808CF3A7）BND-CODE-CONDITIONS／检查展示。独立pending，未合入设计；本文件先于本批代码保存。

## 输入、输出及不变量

复用原C39四步骤、TaskConfigurationApplication、新批准授权和原同组只读核对。输入仍为任务版本、新配置／新适用授权和原因；不增加用户字段、Schema、并行应用表或第二套检查执行器。

第一完整单元允许已封存候选、原窗口CLOSED且检查／模型／问题／权限／未知费用／操作均已结案的VERIFYING任务显式采用新CheckSetVersion。原Git／executor／models／environment／commands／capture_rules／delivery及其他限制保持不变，仅沿用已支持六类控制限制。授权除六类限制外保持同一目录／命令／网络／模型／交付范围。原命令完整定义仍须匹配不可变资源，不把超时字段自由改成未登记命令。CheckSet内的Item.timeout_seconds由既有执行器取与固定CommandDefinition较小值，不能扩大原命令时限。

采用前核对真实当前角色前缀、固定设计依据、CODING owner、完整CheckSet定义、已登记资源与本轮部署的实际项目检查准入；只接受当前受控执行链已支持的CONTENT_INTEGRITY／PROJECT_COMMAND组合，未准入的功能driver不假装可执行。提议校验复用现有检查选择／授权算法，但不能伪造Task当前配置或把APPROVED_UNBOUND授权临时当EFFECTIVE。

原接收步骤冻结非秘密检查组摘要；后台采用前重读同一版本及当前资源／准入，必须匹配原冻结事实。资源撤回／未知时保持原C39及旧组，恢复后只读同一原身份重核。历史读取只复核不可变原版本和已保存事实，不要求旧目录在后续阶段仍在线。原START／实例启动来源、会话／代次／候选不改，不执行检查或模型调用来“验证配置”。

成功后旧Verification／发布／报告均保留历史，旧自检资格按新profile／CheckSet失效；用户明确重新检查才创建新Verification。STOP优先、预算变化的CAS及重复原请求遵循既有C39规则。前端显示当前／目标检查标准版本及需重新自检，UNKNOWN不显示新组生效。

## 后续完整单元

1. 先完成检查选择复用、原接收／采用／保留记录和角色链、离线SQLite／HTTP／资源撤回／STOP与新旧检查资格。
2. 接真实NTFS／Guard原项目命令，以新检查标准对同一候选明确重新检查，再原角色／修复／发布链；前端实际HTTP／Chrome及旧配置回归分开证明。
3. 按正式规则接已发布候选的配置失效恢复：保持原发布及交接历史、未占交付才回VERIFYING／INTEGRATION，重检后回原AWAITING_TESTING；未完成前明确标记。
4. 其他捕获／执行限制、原生permission合并和仍在写入的受控停止另批，不因本限定分支放开。

## 授权和验证边界

本轮用户要求约两小时持续推进，自香港21:38开始。允许源码及相关隔离离线Windows／SQLite／本地HTTP／Chrome／strict／格式／构建；无真实模型／计数、正常业务库写入、用户服务更新、SYSTEM／WFP安装或Git提交推送。所有源码整文件保存先同目录临时文件、fsync、并发字节复核后原子替换；测试临时目录及子进程在成功／失败／取消后清理，只留Markdown汇总。该句所述为21:38启动时边界；当前实际结果见文末实施状态及验证链接，不将启动时记录误当现行状态。

## 21:59 发布后采用实现边界补充

复用 published_check_task 已有原发布证明，把 AWAITING_TESTING／AWAITING_ACCEPTANCE 的真实 Integration 会话作为 C39 输入；原候选／发布操作身份冻结于原步骤，历史读取针对该不可变候选，不能依赖后来 Task.current_candidate_id。接收事务以真实旧状态／阶段作CAS，待核对期间转 WAITING／INTEGRATION，采用后转 VERIFYING／INTEGRATION，清除当前报告与计划引用，旧事实不删除。不产生第二次发布。存在 current_delivery_id 或在途／未知操作时不准入，本单元不尝试撤销已有交付。

本轮浏览器检查按 Playwright CLI 对隔离实际 HTTP／SQLite 执行，分别保留旧控制项与新检查版本场景；原生只读观测是离线驱动，实际 Guard／NTFS 项目命令另列证据。

## 当前实施状态（23:37最终核对）

检查选择／准入、原C39冻结及历史、新标准同候选实际项目检查、已发布AWAITING_TESTING候选恢复、前端实际HTTP／Chrome均完成本限定隔离验证；最新原15秒Git单次上限与完整Guard链783.38秒通过。AWAITING_ACCEPTANCE真实合格报告／Plan联合仍未覆盖；供应方／正式LPAC／SYSTEM／WFP及原生权限热换均未通过，不混入本单元。后续明确输出上限和固定内容授权保护另见同目录两个pending，完整分层证据见[验证](../../../verification/v2.0/coding-check-configuration-2026-11-11.md)。本文件仍pending，未自动合入设计。
