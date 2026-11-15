# 受管目录引用与原生权限编译 V1（V2.0）

2026-11-13，按本轮剩余实际工作时段继续。实施前登记，保留pending，不自动合并正式设计。依据BE OBJ-CODE-POLICY、ConfigurationOption、APP-CODE-CONDITIONS及7.4.4。

## 本批输入／输出与不变量

正式资源仅增加两个抽象READ_ROOT引用：READ20-WORKSPACE-1绑定当前任务真实工作区，READ20-BASIS-1绑定本实例固定只读依据目录。公开value仍严格为{scope_kind,scope_ref}，不登记或泄漏主机路径，不接受浏览器给出的路径／通配规则。元数据ready=false，仍需Q20-CONFIG／Q20-WINDOWS；登记不等于运行准入。

资源定义单独冻结，以摘要绑定编译语义及目录新版manifest。旧catalogue原字节保留，新版本发布到新目录并原子换pin。旧版manifest只读可验证，不允许为旧版添加新目录项。新版本要求两个范围完整覆盖，删除／篡改不能靠重算manifest摘要通过。

原生编译的本批支持边界为无命令／无网络、仅受管workspace及可选basis读范围、write_workspace_only=true。必须明确workspace读取；不把缺失引用当默认许可。输入是严格已保存profile／grant及程序持有的真实NTFS目录身份，原生agent／model固定；编译结果先deny-all，再确定受管读取／编辑规则，外部目录单独约束。超出本批支持的scope／命令／网络一律拒绝，不能降级成全局通配权限。最终生效仍需原配置／provider／会话／Guard组与业务授权核对，编译摘要不冒充OS准入。

## 固定来源

OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c：tool/read.ts／edit.ts的permission pattern是相对worktree路径；tool/external-directory.ts使用独立external_directory并Windows normalize；util/wildcard.ts及core util/wildcard.ts把反斜线转正斜线、*可跨目录、Windows大小写不敏感。不能直接以绝对目录规则替代这组语义。源码按同提交GitHub读取，404的permission/next.ts不作为证据，实际模块位于permission/index.ts。后续补齐原规则求值及路径适配证据。

## 验证

先做资源真实发布／篡改／旧版读取及API20无秘密／只读专项，再做NTFS身份／路径和原生规则边界专项。没有供应方／OS安装／用户库和服务操作；必要临时产物finally清理，仅Markdown保留结果。

## 编译接入原会话生产入口

本批将编译结果直接用于TaskInstanceDriver.create_session：从当前任务同组profile／grant及本次PREPARING会话读取输入：初始START允许原步骤绑定的BOUND_PENDING_APPLY，继任仅EFFECTIVE；不提前写生效状态，编译前后复核同一持久来源；根workspace与basis身份在Guard准备后、进程启动前固定，不能在会话创建时认领当前路径。缺数据库、身份或支持范围一律在原生POST前拒绝。原创建意图保存最终规则，未知恢复继续按原意图读取，不改写请求或重POST。

范围保持read／edit两个权限类别（固定工具集的edit／write共用edit权限）；grep／glob的权限pattern是搜索文本而非路径，无法单凭该pattern约束.git／读范围，因此本批不开放。read目录列表仍可用，固定依据只读，原生其他工具／shell／网络默认deny。此限制不改变正式设计的完整目标，后续命令／搜索能力需独立受管准入与真实范围证明。

## 前端说明与范围显示

任务配置的说明同步包含原启动边界内固定依据的读取授权调整。AuthorizationScopeFacts对两个已登记引用显示“任务工作区／任务固定依据”；历史未知引用继续原样显示，数据及引用比较不变，不发额外请求。实际C39浏览器联通检查应核对目标授权、未知／采用及原请求恢复，不能只用资源目录演示通过。

## 固定原生工具集合的额外边界核对

同一固定提交的tool/registry.ts（Git blob 9167cb3ea6bc5c8dd075f0f8271adbdec6074b12）仅当modelID含gpt-、且不含oss／gpt-4时启用apply_patch，并替换edit／write。当前生产checked_coding_configuration严格固定walle-code／walle-compaction的键与实际id，不符合该选择条件；配置或provider变化仍按原启动摘要拒绝。运行包同时禁止plugin／mcp／experimental扩展。这里依赖固定版本和实际别名，不宣称对任意模型或扩展成立。

已核对apply_patch.ts的移动目标仅执行external_directory检查，最终edit模式列表不含移动目标；因此不能把本批read/edit规则泛化为该工具的完整移动目标保护。本批固定工具集合排除它；若将来更换原生模型标识或开放工具扩展，必须重新验证或补独立边界，不得沿用本批规则。正式OS的basis只读证明仍是独立准入前提，源代码审阅不替代真实执行器验证。grep／glob仍保持deny。

本批实施及分层证据见[本轮记录](../../../verification/v2.0/managed-native-configuration-2026-11-13.md)与[现行需求映射](../../../traceability/v2.0/需求实现映射_V_2.0.md)。目录仍ready=false，正式OS／供应方及完整授权能力不由隔离结果代替；保留pending，不合并正式设计。
