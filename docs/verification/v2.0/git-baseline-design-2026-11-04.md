# WALL-E V2.0 已提交Git版本起点简化静态核对

日期：2026-11-04（Asia/Hong_Kong）。用户明确要求按“起点选一个已提交Git版本即可”修改设计。结果：起点改为原仓库固定commit登记，不再封存起点完整代码包；两份草稿及相关创建、读取、恢复和验收已同步，仍DRAFT。

## 1. 来源、基线与边界

接续后端0.16-draft-16／前端0.15-draft-15，先保存[独立迭代](../../iterations/pending/v2.0/WALL-E.已提交Git版本起点简化迭代_V_2.0.md)，再按原职责同步至后端0.17-draft-17／前端0.16-draft-16。

本轮只修改7份V2 Markdown：两份草稿、独立迭代、两个索引、设计断点和本记录。未改产品源码／SQL／配置／资源／数据，未安装、执行Git写入／真实仓库操作、产品／浏览器／模型／计数、服务启停或提交推送。Git保留引用是未来产品设计，本轮没有创建任何引用。前序迭代／评审／验证保留原字节，未合并V1.5正式设计。

原V2设计汇总及设计建议记录在本轮开始时已不在目录，未恢复；只将当前两份草稿及设计索引的失效链接改为历史来源说明／有效导航，不回写历史验证。

## 2. 设计结果

| 能力及位置 | 最终规则 |
| --- | --- |
| CodeSnapshot／OBJ-CODE-CONTENT | 保留原业务名及base_snapshot_id／snapshot_id引用，语义为已登记Git基线；字段仅id、repository_id、registration_operation_id、content_profile_version_id、commit_oid、content_tree_oid、retention_ref、content_policy_version、registered_at、created_at |
| GIT20-BASELINE-1／7.2.1 | 只登记完整commit OID，源工作目录／索引／未跟踪文件均不纳入。想采用本地修改需用户先自行提交。无提交仓库须先有初始commit，真实空树提交合法 |
| REGISTER_BASE／API-05 | 原POST /code-repositories/{id}/snapshots改为{commit_oid,execution_profile_version_id}；旧观察／文件选择／来源暂停输入移除。VALIDATE_COMMIT→PIN_COMMIT→VERIFY_PINNED_OBJECTS→SAVE_BASELINE，沿原资源Operation／幂等，不创建占位任务 |
| Git保留 | 用户明确登记时在来源仓库create-only创建refs/walle/baselines/{snapshot_id}指向原commit，保证正常Git保留覆盖它；不写用户分支／索引／工作区，不建起点bare包、不提交／stash／fetch。原结果未知只核对原ref／commit／进程，不换ID重发或覆盖冲突引用 |
| 可用性及故障 | 被引用基线不自动删ref／GC。原仓库／ref／对象损坏或删除时CONTENT_NOT_READY，不改用HEAD／工作目录／其他仓库，不自动复制备份。旧“脱离来源仍能恢复起点”保证明确取消 |
| 工作区及Testing | START从原commit／tree读blob，物化独立受管工作区，不另保存起点包。Testing SNAPSHOT也从固定Git读取，CANDIDATE仍从原包读取，任务／预算／停止彼此独立 |
| 文件与差异／API-19 | 旧观察工作目录文件页替换为GET /code-snapshots/{snapshot_id}/files，CodeBaselineFileEntry={path,mode,blob_oid,byte_count}；BASE差异从原Git树读取。RepositoryObservation只保存原HEAD／分支／worktree元数据，不再设计source_entries存储 |
| 候选与Plan | CodeCandidate及交付目标Plan继续CONTENT20-STORE-1自包含包、manifest／seal／发布恢复；候选静止／检查／报告／接收及完整停止门槛不放宽 |
| 前端创建／恢复 | 来源提交文本初空，可明确从观察的分支条目填入当时完整OID或粘贴提交；移除未跟踪选择、暂停写入复选和起点封存进度。显示所选commit／登记时间／可用性，提示原仓库需可读。REGISTER_BASE普通原键恢复，交付一次性确认继续QUERY_ONLY |
| 数据库200 | CodeSnapshot只映射上述10项元数据及原ref；registration_operation_id和(repository_id,retention_ref)分别唯一。删除旧起点content_store_key／manifest／source_head／captured_at等列设计，候选列及V1.5旧值保留；本轮未生成或运行SQL |

选择版本本身只读，登记才创建保留引用；文件GET不创建／修复ref。提交合法但模型／执行器未就绪不阻挡版本登记所需的内容／Git校验。基线源不可读会阻断START、SNAPSHOT测试及BASE读取；候选／Plan固定包继续按自身内容读取，报告／交付资格仍单独复验。

## 3. 实际静态核对

使用rg定向检索旧CAPTURE_BASE／来源确认／未跟踪选择／CodeSnapshot包字段／旧观察文件页及其验收残留；内存Python检查字段表—正文成员—200映射、116接口与客户端路径、基线10字段精确集合、API-05／19请求响应、恢复方式、Markdown结构／本地链接／目标场景唯一性及既有重要契约。未保存脚本、JSON报告、截图或原始日志；git status --short、rev-parse HEAD及diff --check仅只读。

结果：

- 16个对象分组、20个应用能力、521行字段／42组记录、116个接口保持清晰；基线由13项包型字段收敛为10项版本元数据，没有新增并行实体或账本。直接成员、OBJ／APP引用及本轮提取的客户端路径无缺项；旧起点捕获输入／包字段／工作目录DTO无现行残留。
- 7份本轮Markdown的本地链接、表格列数／围栏／版本／空白及唯一当前断点核对通过。外部链接未重新联网验证。
- 既有TC20-05／63、前端来源／恢复及原观察案例按新规则重写；另新增后端TC-GB20-01—08、前端TC-FE-GB20-01—04，共12项目标，累计后端162项／前端110项。本轮产品场景执行0，4项EV仍未执行。
- 52份保护文档及283份backend/app／frontend/src源码摘要与本轮开始一致，既有V1.5及其他任务改动保留。HEAD保持8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，git diff --check通过，本轮原子临时文件0。
- 静态检查发现的重复错误编码已去重；当前失效历史来源链接已处理。没有用静态核对代替Git引用保留、Windows物化或故障恢复的运行证据。

| 草稿 | 接续SHA256 | 收口版本／SHA256 |
| --- | --- | --- |
| 后端 | 7c752894ccdf471442fa8da22edcc99551327cdf27052cd82657fb256db98a4b | 0.17-draft-17／1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37 |
| 前端 | 130aa5ba2ad41f440fce057c81644477ffb49f361766ea205662d4128244d39b | 0.16-draft-16／38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7 |

## 4. 尚未实施与接续

真实REGISTER_BASE／保留引用、原对象读取、API-19及差异、521字段对应200结构、前端版本选择和原键恢复均未实施／运行验证。Git保留与未知结果、源仓库丢失、实际Windows路径／模式／秘密／容量校验、独立Testing物化等证据后续单独取得；Git／Windows／执行器／模型／数据库升级原ready=false边界保持。

本轮没有产品进程、真实ref、SQL、资源安装或源码半成品。当前完整接续见[设计进度](../../project/v2.0/设计进度_V_2.0.md)，独立迭代继续pending，不等同正式定版、代码完成或软件验收。
