# V1.5 计数字节容量与负向收据离线专项

2026-10-24，Windows PowerShell、项目.venv Python，当前保存工作区；资源v13 OFFLINE_READY。范围：供应方text UTF-8合计容量预检、调用额度、成功响应有界读取、摘要收据只用于超预算否决、任务失败反馈、正常审计及取消／恢复／准入。所有专项只使用临时SQLite及私有计数／Chat代理或本机loopback；无真实供应方、用户数据、用户服务或Git写操作。

设计：正式BE AI-RESOURCE第7项，当前SHA256 fd231a9d32300bce072f07d628b617ff449a18e6b012e35999eed7f245030be8；模型可见Schema／Prompt／Wire未改。v13 manifest 6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d；release eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68；采用时BE摘要901f…保持原值。backend/app当前Python源码聚合SHA256 67a8f51d3c96b5949e9204c2288680009330dfb3baee31a454d2fb1530178050（按项目相对POSIX路径排序，依次加入路径UTF-8及文件SHA256二进制摘要）。

定向命令：`.venv/Scripts/python.exe -m pytest backend/tests/infrastructure/test_tokenization.py backend/tests/guide/test_v15_counting.py -q`。19 passed、13 subtests、41.11秒，1条既有Starlette提示。覆盖800000精确边界／800001本地停止、多字节／重复／空串、JSON转义大小不同、无外推legacy模型、8MiB读取／4MiB持久边界、摘要不能批准或重放合格最终候选。

首次工具联合：count_probe＋evaluation_tool，11 passed／5 failed，46.39秒。失败为检查期间准备器报告字段再次修改但最终固定源码哈希未同步，原保护正确拒绝；已同步3730…，不放宽输入固定检查。最终结果在下方记录，不将失败删去。

扩大命令：`.venv/Scripts/python.exe -m pytest backend/tests/infrastructure/test_tokenization.py backend/tests/infrastructure/test_counting_journal.py backend/tests/guide/test_v15_counting.py backend/tests/guide/test_v15_execution.py backend/tests/guide/test_v15_observation.py backend/tests/guide/test_v15_count_probe.py backend/tests/guide/test_v15_evaluation_tool.py backend/tests/guide/test_v15_admission.py backend/tests/guide/test_v15_recovery.py backend/tests/guide/test_v15_worker_recovery.py backend/tests/guide/test_v15_usage.py -q`，11文件，session26313已结束：87 passed／1 failed／24 subtests，478.72秒。唯一失败为完整26输入的离线计数fixture仍按>400000字符伪造HIGH；新必要全文约266KB，故未产生测试所期待的HIGH。实际程序保持0Chat并正确报告未触达，未错误放行；已将私有fixture改按“必须完整检查的来源”显式标记选择假计数，不通过文本长度猜真实Token。业务代码未再修改。此项及新增实际4—8MiB数组loopback／正常运行本地超限释放正在独立复验（session66112），未声称全11文件重新跑通。

独立静态／准备：资源正式设计源专项1 passed／3.27秒；v9—v13各21项资源长度／SHA逐项通过。v12技术＋26EV的108个正常SQLite／计数审计文件只读核对聚合SHA仍61e51eb528ef7edbf366c2e3855f331320cd961c76fd21a7759f79bf37e15ce9。最新诊断只读run CANCELLED／根IDLE／LLMUse0。`git diff --check`通过（既有CRLF规范化提示）；cleanup-test-artifacts.py --dry-run为JSON0、screenshots0；8000／5173无监听。没有前端改动，本单元不重复已有前端类型检查／构建，旧结果不当作本次新结果。

固定输入：prepare-v15-evaluation.py SHA256 3730fbbe9b0c2067f6006dd08d3ea19df90236945ceba8cbe2ac5bb904f7d8aa；runner 9b34ddb2b577b7e370133a5d7018017fcac39cef8d41500341b7599a1e92cd4b；纯计数工具41cfeb0f9560ead43e75d37770b7db61943e81b59fe910492299d88ca07121a1。两领域必要全文预编译通过，实际八段546366／546384字节，详见[输入准备](ev-input-byte-capacity-2026-10-24.md)。原8000行来源原字节6b0de89d…保留，旧真实结果不覆盖。

未覆盖：新4000行输入的真实计数及Token门限、v13技术Chat准入、真实26EV复验、自然截断及候选后处理、人工语义。旧许可全部已消耗，无新调用。旧13个锁文件Temp目录及本轮初次失败3个隔离测试目录的精确删除被自动审批拒绝（blocked by policy，未给细分原因），未绕过，遗留清理项保持；新修正专项正常清理临时目录。

最终定向复验已结束：session66112，`pytest`精确执行test_v15_evaluation_tool.py::test_all_fixed_inputs_execute_once_with_private_providers_and_real_postconditions、test_tokenization.py::TokenizationTests::test_real_capacity_large_arrays_are_fully_validated_before_summary、test_v15_count_probe.py::test_original_oversized_fixture_is_preserved_and_rejected_locally_without_count_or_chat，3 passed／151.02秒（1条既有Starlette提示）。完整26输入及6个候选后处理通过，固定旧输入在正常编排产生本地PROVIDER_INPUT_LIMIT／0计数发送／0Chat／根IDLE；真实4—8MiB完整数组先校验再摘要，最后一项数组无效仍拒绝。生产代码与87通过时相同；没有把此结果写成全11文件再次跑通。全部本轮检查进程已结束，临时数据正常清理。
