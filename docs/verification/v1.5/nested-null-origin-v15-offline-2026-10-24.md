# V1.5 v15嵌套空字段、来源指引及EV停止保护

2026-10-24（Asia/Hong_Kong），Windows PowerShell／项目.venv Python，当前保存工作区。真实v14技术＋26EV已完整结束，29计数／25Chat／265572 Token，未续用上限。19份EV validation成功，3份分量失败与两份真实截断均保留，正常程序边界见live-verification-v14-once-2026-10-24.md。

v15只明确原约束：required对每层对象有效，CLARIFICATION的action_payload必须JSON null；自由输入偏好／纠正／明确生成的来源仍为USER_STATEMENT，保留其业务约束和已绑定生成授权，不冒充正式卡片采用。Schema／Wire／C07／来源、预算、模型均未放宽，不补字段或改写旧返回。正式BE SHA256=9f7e6476861e8d954fc6be675973c6e829988b2c582a107367b3d764fb90bcdd，资源v15 Prompt v6／release v7，manifest a8c5087236d8e4b4b40d62a92643832fe37cc2b5e426725f1ddde7d5670abc40，release 5ced9443c445aa10330e906a875fd4dafe69b6ebe0eb5e40179251b5eefb5d97，OFFLINE_READY。

评测器另外修复真实调用停止边界：ModelGateway可返回失败TransportResult而不抛异常，本地终态不能证明远端已知。额度包装记录失败／缺失传输证据，当前样本落正常审计后结束批次，不继续下一样本；成功外壳下的无效或自然截断模型内容仍单独记录，不误作网络未知。此缺口在本轮25次实际SUCCEEDED调用中未发生；原v14结果不改写。原执行器14423b11…已原字节冻结sources/v1.5/run-v15-evaluation-v14-frozen.py；新执行器SHA256=21bfb89a6933de8ac25b2dd125682352dcbc231018ebc38b69fa966d921545a3；固定输入a6b92ffe…与纯计数工具4425ecfe…未改。

定向命令：`.venv/Scripts/python.exe -m pytest backend/tests/guide/test_v15_execution.py backend/tests/guide/test_v15_evaluation_tool.py backend/tests/infrastructure/test_collaboration_resources.py -k "clarification_null_payload or failed_transport_stops or resources_match_the_complete_design_source" -q`。5 passed／55 deselected，36.53秒，1条既有Starlette提示。包括完整源一致性、嵌套null缺失／合法时进度独立、失败传输有／无响应而运行已终态时整批停止，无后续目录或发送。

相关联合命令：`.venv/Scripts/python.exe -m pytest backend/tests/infrastructure/test_collaboration_resources.py backend/tests/guide/test_v15_execution.py backend/tests/guide/test_v15_progress.py backend/tests/guide/test_v15_cards.py backend/tests/guide/test_v15_counting.py backend/tests/guide/test_v15_admission.py backend/tests/guide/test_v15_observation.py backend/tests/guide/test_v15_evaluation_tool.py backend/tests/guide/test_v15_model_calls.py -q -p no:cacheprovider`，9文件session91654已结束，退出0：108 passed／528.28秒，1条既有Starlette提示。全部隔离临时库／私有代理，零真实IO或用户服务变更；不能用离线通过代替v15供应方效果。

静态核对：v9—v15全部资源长度／SHA通过，v15相对v14仅Prompt及release变化，其余19资源同字节；112个v14正常证据聚合SHA仍ee4f872ee31e81f832ec16546dae3b7980f083a51dee8bd8f3bbde7b416f3d0b。backend/app源码聚合SHA256=9cf0a135b6232d593716a0cf576d71c285756265ba6a07ad6e156660a80358f5（项目相对POSIX路径排序，路径UTF-8＋文件SHA二进制）。前端未改，本单元不重复其类型检查／构建，旧结果不当作新结果。旧Temp删除审批拒绝项不绕过，正常业务／观测审计不删除。

未覆盖：v15真实技术／结构／效果复验及人工逐项语义；v14原语义仍待人工审阅，3分量失败不改成通过。旧付费许可全部结束，新的实际调用仍须新明确预算、槽及次数许可，不自动换版本重测。

最终静态及清理：git diff --check通过（既有CRLF规范化提示）；cleanup-test-artifacts.py --dry-run为JSON0／screenshots0；8000／5173无监听，无正在执行的本轮检查／真实进程。旧审批拒绝的13锁文件目录及3临时隔离库目录保持遗留，不绕过清理；正常真实证据不删。此前v14相关129项是旧Prompt基线，不代替本次新108项，也不机械累加成一个全量结果。
