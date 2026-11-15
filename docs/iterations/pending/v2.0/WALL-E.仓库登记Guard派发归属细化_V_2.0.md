# 仓库登记原 Guard 派发归属细化（2026-11-07）

来源为后端设计 OBJ-CODE-OPERATION、APP-CODE-SETUP、7.3.3、7.7.6，以及已确认首次登记预留 ID 和原 202。未合入正式设计。

## 最终实施规则

原登记只有 VALIDATE、SAVE_FACT 两个业务步骤。VALIDATE 的 code_operation_steps.external_identity 继续保持原“只写一次”约束。其私有 git_launch 只固定实际控制方引用、epoch、程序生成的原随机 nonce、命令及后端私有原记录根 FileID。所有权、步骤和原字段均不改写。公开投影继续隐藏私有身份。

后端复用 LaunchJournal 的原 scope 门、operator-only 私有包及 PrivateRecordAppend，追加固定 GIT_LAUNCH_ACTION 证据。每个动作分别有不可覆盖的 MAY 和 ACK 记录，固定文件身份由原 scope／动作／阶段确定。先保存 MAY，再离开事务及 scope 短门通过原受控管道发送；ACK 完整保存原资源和实际进程身份后才可发送 RESUME。PREPARE 回执和 CREATE 回执的事实保存在原步骤指向的私有证据中。该机制不创建额外业务步骤、占位仓库、任务或第二个业务状态机。

一次原 VALIDATE 仅可预留一个配置解析 scope。重启、提交或回执未知只核对原记录，禁止新 nonce 或重新派发 MAY。STOP 和 RELEASE 也有独立原意图和证据。技术记录不保存配置正文／stderr。业务发布仍需实际输出解析、原源与原元数据复核及完整释放，公开回执保持原 202。

## 被替代尝试

最初将动作状态回写 external_identity，隔离测试被 ORIGINAL_FACT_IS_FIXED 拒绝。该尝试已替代为固定指向和追加原证据，保留原数据库触发器及 Schema，不放宽原事实不可变规则。

原 OBSERVE 回传该原动作输入摘要与已持久 ACK。后端仅在摘要与自己的原 MAY 完全相符时补存同一 ACK，原 scope／动作不变，不重新发送副作用请求。实际进程和 Job 的当前观察仍单独核对。

## 内部 runner

登记 runner 在原接收后启动 VALIDATE、预留原 scope，按实际非提升后端账户打开原位置和配置导出。固定配置解析、原挂起关联、恢复、输出捕获、原根退出、原 STOP 及空 Job 观察、RELEASE 全部沿同一 scope。只有原配置输出完整、源与元数据重验且释放回执已持久，才发布完整仓库。执行为有界单次尝试；失败或未知时保留实际本地源／I/O owner，向调用方返回原 owner 以继续原步骤核对，不能自动开始第二次执行。宿主仍须负责在途 owner 的生命周期及重新建立的原鉴权连接。

同一存活后端可重新建立实际鉴权管道，凭原 PREPARE ACK 和原 scope 继续 STOP、当前空 Job 核对及 RELEASE。已存在 MAY 时先 OBSERVE 同动作、同摘要，不能重发。恢复清理不恢复 Git、不生成新 nonce、不发布仓库，业务 UNKNOWN 保持；缺原 PREPARE ACK 或原 owner 时不报告完成。
