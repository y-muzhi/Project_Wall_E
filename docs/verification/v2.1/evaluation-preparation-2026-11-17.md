# V2.1模型评测离线准备与观察入口衔接

日期：2026-11-17，Asia/Hong_Kong；本批20:35接续，用户要求按两小时工作量推进。工作区codex/v2.1-design-review，HEAD a0f40592702cb702ed928849ac540479c22c224f，检查保存的连续未提交改动，不提交推送。Windows固定SQLite3.54.1/Python3.13.5/Ruff0.17.3；本批无前端源码改动，无用户服务更新、正常业务库操作、真实Tokenization或Chat。

## 当前范围

后端0.1-draft-4第4/6/8.1/8.3节，原文SHA256 4049f8d3b5d01bd704dd0439b8c0730155cec813f3f5ef8ef7ad8c5ba5b5b197。独立迭代先于生产修复写入，正式设计保持DRAFT且原字节未改。

生产修复仅[CollaborationObservation](../../../backend/app/infrastructure/collaboration_observation.py)：旧目标空值校验阻止V2.1明确绑定文档的DISCUSS。按release核对target，新formation还需同文档冻结DISCUSS/expected V1/空allowed_targets；单隔离库、单文档、单Run、空正文和原调用前预算保持。普通HTTP/Worker不能构造该私有能力，不修改全局LIVE。

配方/工具：[spec](../../../tools/formation_evaluation_spec.py)、[fixture](../../../tools/formation_evaluation_fixture.py)、[输入编译](../../../tools/formation_evaluation.py)、[入口](../../../tools/prepare-v21-evaluation.py)、[双人汇总](../../../tools/formation_evaluation_review.py)。正常创建/人工编辑/真实结束/C01/Artifact核实与SQL历史前置分别注明；不是全量8.1 FBASE，未伪造旧卡或历史模型调用。8例结束后改稿，原Closure保持。暂缓i2的真实用户决定与未携带实体区别保留。

## 当前唯一评测输入

| Profile | 当前清单 | 样本/候选 | 生成 | 全量重建 |
| --- | --- | --- | --- | --- |
| deepseek-v2 / v27 | [默认](evaluation-inputs-default-2026-11-17-r2.md) | 60/120 | 100.37秒，通过/清理成功 | 99.31秒，通过/清理成功 |
| deepseek-long-v3 / v28 | [长输出](evaluation-inputs-long-2026-11-17-r2.md) | 60/120 | 100.55秒，通过/清理成功 | 98.12秒，通过/清理成功 |

分别运行prepare-v21-evaluation.py --profile <固定配置> --manifest <新清单>，再以--verify <同清单>重建全部行及正文。每组固定12×5，候选沿生产full/no-history/required去重；实际均2候选/样本。逐候选核对Canonical/system/Wire/Output/八文本/实际HTTP请求/覆盖摘要、Profile及配方原SHA。八文本通过原check_text_capacity字节检查；不是Token测量、真实兼容或语义通过。120/240是输入候选数，不是模型成功次数。

最终两组默认60样本与长输出60样本彼此独立，不借结果；实际尝试0、人工评价0，全部NOT_RUN/PENDING。Profile SHA沿生产release，Request SHA沿ModelGateway真实保序UTF-8 content；排序JSON仅用于集合/配方管理摘要。

同日较早的[evaluation-inputs-frozen](evaluation-inputs-frozen-2026-11-17.md)、[v2](evaluation-inputs-frozen-2026-11-17-v2.md)、[r3](evaluation-inputs-frozen-2026-11-17-r3.md)、[baseline](evaluation-inputs-baseline-2026-11-17.md)、[current](evaluation-inputs-current-2026-11-17.md)原字节保留，仅作本轮构造过程追溯，不是现行输入。其后依次补齐源码/资源指纹与预算元数据、已结束状态、生产请求/Profile字节顺序、目标观察修复及两配置支持；另[默认初次双配置清单](evaluation-inputs-default-2026-11-17.md)与[长输出初次双配置清单](evaluation-inputs-long-2026-11-17.md)在最后严格类型收口后亦由-r2替代，原98.39/97.55秒生成及109.44/108.98秒重建为当时实际结果。旧配方清单以当前入口verify实际拒绝Recipe differs，不能用于启动真实评测。

## 实际检查

- 工具边界：前轮本批15项/11子检查通过4.24秒；实际ModelGateway以MockTransport拦截发送内容，中文/换行/字段顺序摘要与真实HTTP content一致，默认Profile摘要与release一致。后续补长配置及最终联合结果在本节最后追加。
- 旧检查入口库存/失败/清理边界4项通过0.041秒；新增观察文件按自动库存进入programs，现56文件（core10/programs22/ai22/load2），没有漏选或声称新standard/all完整重跑。workflow仅新增工具边界检查，未推送/触发GitHub。
- 观察新专项先7项通过32.73秒，扩展原C07/审计/后续隔离运行后8项通过45.88秒，1条既有警告。首观察1次替身计数/Chat、之后另库1次普通替身C07；两文档V1/V4和原审计保持。Schema210源只读证据校验/导入实际经过生产机制。
- 旧观察与长输出18项在首次联合运行中通过；该联合总结果为20通过/5失败（135.56秒），失败全部为新增反例试图修改已接受字段触发IMMUTABLE_FIELD。随后仅修正反例工具，不关闭触发器，不改变生产不可变约束；以真实事务的查询边界注入错误值，原行不变。不能把首次联合写为25项全绿。
- 新反例覆盖未绑定target、写授权、其他文档授权、V依据错误、缺失授权、真实已有正文；0调用校验阶段即拒绝。普通Worker/命令不能装观察能力沿旧专项回归。
- backend/app588文件格式通过；本批新增/修改Python文件F/I/B及锁定格式按最终回收追加。前端650/类型/构建、23页面场景与长负载为旧批证据，本批未机械重跑，不变更其原日期。
- 受限Windows进程中的直接异步unittest曾无输出等待，已停止所属会话；在允许本地异步通信、仍禁止外网/正常库/凭据读取的隔离入口中通过。未恢复已取消的Windows Node崩溃专项，未以此宣称旧Node异常已解决。

观察专项中的LIVE_VERIFIED仅为临时替身业务库的程序状态；测试目录及其正常审计/准入文件自动清理，没有为正式资源或用户库授予真实LIVE。本轮不存在实际供应方用量或真人评价。

## 已修正的准备工具假设

首次使用FormationDatabase漏显式release、UUID5不符合原UUID4请求键、试图清不可变幂等记录、Artifact事件漏formation_event_type均在离线夹具构建时失败；已按生产约束修正，保留成功回执，不改数据库触发器。最初摘要对Profile/请求体用了排序JSON，已改为生产保序字节并加实际Gateway传输证明，旧清单不冒充现行。上述全部先于任何真实API，原始输出仅内存。

## 未覆盖/后续

两配置均未获/未执行真实预算；真实供应方协议/效果、两名独立人工、全局LIVE、真实读屏、正常库/用户服务切换、正式设计合并和提交推送均未完成。本批准备/Mock不能替代这些事项。操作及配额边界见[实施说明](../../project/v2.1/模型评测实施说明_V_2.1.md)。

21:28正式只读现场：8000/PID183580与5173/PID41048仍为用户原服务，8217/5187无监听；受限视图为空不能视为已停止。工具只用自有临时目录，无自有页面/浏览器服务。最终原摘要、链接、产物和进程回收另追加。

## 最终专项回收

最终固定SQLite/隔离入口执行tools/tests/test_v21_evaluation.py、test_v21_evaluation_transport.py及backend/tests/formation/test_v21_evaluation_bootstrap.py：**24 passed, 13 subtests passed，62.61秒，1条既有警告**；父步骤63.86秒，清理成功。包括默认和长输出首样本只读能力校验，模板/重试/预算/分母/真人身份元数据、真实MockTransport字节及原C07双库衔接。9个本批Python文件F/I/B及锁定格式通过，backend/app588文件格式通过。

默认/长输出分别重建完整60样本/120候选并逐行/完整正文相同，源配方SHA在运行中保持；两次清理均成功。实际Tokenization/Chat仍0。全NOT_RUN登记与UNASSIGNED模板重新绑定现行清单，没有人工数据被覆盖。实际CLI未分配评审者拒绝汇总且无新报告；显式跨Profile重建拒绝，未进入模型执行。

## 严格类型最后收口（覆盖上一节的最终版本）

对私有观察JSON依据补充boolean_content_basis实际反例：原Python等值判断未拒绝True==1，1项失败/11项未选，5.50秒；普通C01/Canonical与SQLite不可变保护已有严格约束，本反例是在只读查询边界注入，不是实际HTTP写入越权。已先更新独立迭代，再对目标及V依据明确type is int，排除True、1.0及42.0。3项反例随后14.08秒通过，未动触发器或放宽业务约束。

最新联合**27 passed, 13 subtests passed，93.89秒，1条既有警告**（父步骤94.52秒/清理成功）：工具15项、观察12项。最新两配置-r2生成100.37/100.55秒、全量重建99.31/98.12秒，均一致/清理成功；Cohort不变，输入配方SHA按修正后的生产代码重新冻结，早期冻结原字节不改。此前24项联合及较早构造记录仅代表原时点，不覆盖本节。

## 22:22最终回收

36份相关Markdown共509条相对文件链接无缺失，A01—A76/TC-FE-01—23身份保持唯一；正式前后端原文、core/r54、target/r7及v27/v28六个原SHA保持，生产资源加载器验证仍为OFFLINE_READY。两个当前-r2配方SHA等于当前生成源码，Cohort与类型修正前输入相同；六份登记/评价模板只在全NOT_RUN/全PENDING且UNASSIGNED时重绑，无真人资料被覆盖。

cleanup-test-artifacts.py --dry-run结果JSON=0/截图=0，工作区无本轮遗留.tmp，git diff --check通过。HEAD保持a0f40592702cb702ed928849ac540479c22c224f，连续227项短状态条目不等于本轮新增或全部已验收；未提交/推送。22:22只读核实8000/PID183580、5173/PID41048仍运行，自有8217/5187无监听，全部自有评测/专项进程已退出。临时库/计数审计/局部替身准入文件按所属TemporaryDirectory清理；未读取或清理用户正常业务库。

本轮可接续断点已保存，实际模型/计数0、实际独立人工0；没有把离线输入/Mock/格式检查当成真实供应方、读屏或整版完成。
