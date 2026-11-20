# V2.1首轮真实问题修复与离线复核

日期：2026-11-18。用户选择先修复再验收，不启用试用。首轮60 Chat许可已用完；本轮修复阶段真实Chat/Tokenization均0，新默认组尚无真实效果/准入结论。

## 修复范围

- 新v29/v30、Prompt v9：明确本轮任务优先级、DISCUSS提案与实际写入的边界、t/s引用域、公开四项FormationBasis、完整成果映射/依赖转交、单顶层块补丁，以及关联/充分性所需实际依据。保留九根/八计数/原C01-C07和事务门禁，没有自动修复或重试。
- Fixture formation-ev60-2仍保留原12基元×5任务/60身份，显式背景/任务优先级，EMPTY_DOCUMENT纠正为实际FILL_EMPTY，依赖纠正为s2依赖s1、s3依赖s2。旧轮样本依赖方向有误，24拒绝不能全部归因模型；新旧输入不同，不能直接宣称同输入效果提升。
- 只改资源固定摘要/默认2.1选择，旧v27/v28仍可按原release读取。Schema210/db21-r7、core/db20-r54及正常数据不变；OPEN材料选取/100项上限不扩大。未携带的DEFERRED实体继续只保留原归属状态，不暗中读取或MOVE。

代码：tools/build-formation-resources.py、formation_evaluation_spec.py、formation_evaluation_fixture.py、formation_evaluation.py、formation_evaluation_execution.py；backend/app/infrastructure/resources.py及collaboration_resources.py。新增test_v21_live_fix_examples.py，并更新资源/首次观察/执行上限的清单绑定检查。所有源码使用同目录临时文件fsync与原子替换，固定资源使用完整目录发布，旧资源原字节保留。

## 实际检查

1. 固定SQLite＋quality_python离线保护，TemporaryDirectory独占；范围为新14个合法/反例C01-C07、资源、context/results/publication、评测工具/预算：75 passed，13 subtests，367.64秒；1条既有Starlette/httpx告警，清理通过。
2. 新14例包含两种正文×五任务，原私有Observation在隔离库取得模拟技术源，其后普通C07只读核对原源；合法路线包含完整两类成果承接/依赖转交/问题支线返回，反例仍整体拒绝。正文/Revision/步骤及原Closure保持；没有把Mock称作真实模型结果。
3. 新清单绑定后的bootstrap、执行审计、评测工具/transport/预算：38 passed，13 subtests，114.98秒；同一既有告警，清理通过。与第1组部分重叠，不称113个独立用例。
4. 588个backend/app格式通过；改动文件Ruff F/I/B及9文件格式通过。12处既有导入/未使用项用stdin修复后原子写回。git diff --check通过。
5. 两个新配置分别冻结60样本/120候选、清理通过。完整--verify重建：默认100.26秒、长输出101.02秒，全部行/摘要及完整Markdown一致，Chat/计数0。两次提升权限的复核启动审批超时未执行，改用普通权限运行同一离线操作通过，没有审批阻塞。
6. 六个旧设计/Schema/资源manifest摘要不变；v27/v28完整文件校验通过，Prompt仍v8。Schema210启动离线检查通过，新资源仍OFFLINE_READY；执行器默认元数据检查通过，密钥/数据库/供应方/服务启动0（该检查命令范围）。
7. 现有8001直连与5174代理GET正式/api/v1/requirements均success=true/items1；未重启或更新服务，原8000/5173不动。未执行前端源码改动/重复前端构建或长负载。

## 当前唯一输入

| 配置 | 当前冻结清单 | 资源 | Manifest原始SHA256 |
| --- | --- | --- | --- |
| 默认deepseek-v2 | evaluation-inputs-default-2026-11-18-v2.md | v29 | 4370628898546323bb98f8002fe5f5af94cbd1943bdccba6aeb051576aa92212 |
| 长输出deepseek-long-v3 | evaluation-inputs-long-2026-11-18-v2.md | v30 | 66903e39d0c5cf2d0e04f1a45d5d2b91520271b6c56719c915084a6ccb97b457 |

共同Recipe SHA256：0c18f729198751b25c18ef08242ea33540ca86ead46a83b89a611088203a048a。
默认cohort dc9c679e3732a713b369a67649d2f6bc05c1f6d93e248bb298683873e77d2b0f；长输出12de93a21786374f860e644f6536493957b07031da94b1e9dfd48036bd75990d。两组独立，不互借评价。

新v29 manifest a2264f7ba58c7bca3a5b662c972a9bf3f866e7496ccf07b92c8fd2f7298ec08a，release b49fd3a297e24ca950dab269769b9189b140914f8a17c031ed8a5ab1755cb5d0。
新v30 manifest1ae4a50c73ebf7ebd3e7c177625a3d0e836058da0808de8bbfee404e7767785c，release2e53264bcfebdbdd74b8db45ddfa4264582162ccd0ea7694b5fe712a7c239e82。

付费入口现在只绑定新默认清单及原始SHA；旧真实目录v21-ai-admission-20261118-01禁止重跑。新的尝试/双人模板为evaluation-attempts-default/long-2026-11-18-v2.md及evaluation-reviewer-default/long-a/b-2026-11-18-v2.md，全部NOT_RUN/PENDING/UNASSIGNED；没有代填人工结论。

## 下一轮边界

待明确授权新默认v29组：最多60 Chat、120必要八项计数，单次输入131072/输出8192/总139264，Chat合计上限8355840 Token，0自动重试，结果不明确即停止。长输出不包含。新唯一数据槽预定data/v21-ai-admission-20261118-02，报告ai-admission-default-2026-11-18-v2.md；尚未创建/执行真实槽，费用未知。旧技术准入不放行新release，新组真实结果及独立人工仍需分别完成，正式AI尚未启用。
