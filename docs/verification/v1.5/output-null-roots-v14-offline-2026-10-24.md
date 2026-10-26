# V1.5 v14必填空字段指引离线验证

2026-10-24（Asia/Hong_Kong），Windows PowerShell、项目.venv Python；当前保存工作区。v13真实条件批次总2计数／1Chat已按首轮结构失败结束，原结果保留，26EV未发送。缺失document_result／suggestions／analysis三个必需null根字段是本次确定原因；不会补旧字段后标通过或续用剩余上限。

正式BE共同Prompt第四段显式列九根字段和JSON null规则；BE SHA256 8c818b009879ce902b9ef2e2692028013437cc47a801d32b5ac7e484c38e80f0。新resources/v14（Prompt v5／release v6），manifest 0353339a82a64183da576c460b538df3c97edd9c7d59d2dd518898ed5557b76b，release ac9c887f0dc52482d7cc329a0faaeb2cfd2e3f69c8e6f89df90f5d16b7a21d14，OFFLINE_READY。相对v13仅共同Prompt及release变化，其余19项实际字节相同；v9—v14全部资源长度／SHA逐项核对通过。未改Schema、Wire、C07、输入夹具、预算或模型；不继承旧准入。

实现：build-collaboration-resources.py新增不可覆盖--v14入口，collaboration_resources固定新manifest，新增四个实际隔离C07场景。backend/app Python源码聚合SHA256=3820e7dad052feade4125d928a9869fea23fce9fdd0c9cbfb20dbd597e3878e2（项目相对POSIX路径排序，路径UTF-8＋文件SHA二进制）。正式输入生成器仍a6b92ffe…；两个真实执行工具仍14423b11…／4425ecfe…，本次不换已发送v13输入后重试。

定向命令：`.venv/Scripts/python.exe -m pytest backend/tests/guide/test_v15_execution.py -k missing_required_null_roots backend/tests/infrastructure/test_collaboration_resources.py -k "missing_required_null_roots or resources_match_the_complete_design_source" -q`，实际5 passed／41 deselected，33.26秒（1条既有Starlette提示）。覆盖缺任意一个／全部三个null根字段时：原始返回完整可读、parsed仍缺原键、trusted为空、进度不应用、pending保留、根IDLE，无新增文档或卡片；以及完整正式设计源与新资源逐字一致。程序不自动填null来通过。

扩大命令：`.venv/Scripts/python.exe -m pytest backend/tests/infrastructure/test_collaboration_resources.py backend/tests/guide/test_v15_context.py backend/tests/guide/test_v15_counting.py backend/tests/guide/test_v15_execution.py backend/tests/guide/test_v15_progress.py backend/tests/guide/test_v15_recovery.py backend/tests/guide/test_v15_worker_recovery.py backend/tests/guide/test_v15_admission.py backend/tests/guide/test_v15_usage.py backend/tests/guide/test_v15_observation.py backend/tests/guide/test_v15_count_probe.py backend/tests/guide/test_v15_evaluation_tool.py backend/tests/infrastructure/test_counting_journal.py -q -p no:cacheprovider`。session96117已结束，退出0：129 passed／11 subtests，579.03秒，1条既有Starlette提示。所有计数／Chat均为私有离线代理，数据库用TemporaryDirectory清理，不代表真实供应方效果。

本单元未启动服务、不写用户库、不做Git提交推送、不调用真实模型／计数API或模型裁判；前端未改，不重复其既有类型检查及临时构建。真实v14兼容／准入及26EV仍未验证，下一次真实动作须新明确授权。原正常库、计数审计及冻结v9—v13资源保留；旧Temp删除自动审批拒绝项不绕过。

独立只读／准备：`prepare-v15-evaluation.py --case analysis-required-over-budget --report docs/verification/v1.5/ev-required-input-v14-offline-2026-10-24.md`两领域实际预编译退出0，临时库清理、0真实IO。v14八段合计546879／546897字节；电影user仍266035字节及2fd3a36b…，与v13阶段1实测U153785的原文摘要完全一致，此事实不是v14正向技术准入或新计数。原7正常证据聚合SHA仍3bfac2b0e14befd5be3a1d9a69517281a239111f5c476ce7a2fccd15db7a7a80；旧v12的108个仍61e51eb528ef7edbf366c2e3855f331320cd961c76fd21a7759f79bf37e15ce9。`git diff --check`通过，仅既有CRLF规范化提示。

当前v14历史读取：独立只读脚本用SQLite URI mode=ro、query_only及只读事务读取原v12技术／26EV与本轮v13技术的26个实际LLMUse，get_model_call全部READ_OK／8分区／8计数。脚本显式禁止compile_context、TokenizationGateway.count、ModelGateway.send及socket.connect，不重建旧快照或发IO；session4222退出0，原validation FAILED保持。cleanup-test-artifacts.py --dry-run为JSON0／screenshots0；本轮全部检查进程已结束，正常旧库及审计保留。
