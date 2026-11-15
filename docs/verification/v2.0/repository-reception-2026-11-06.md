# 仓库原操作接收与发布检查（2026-11-06）

## 范围与代码状态

V2未提交工作区；BE0.17-draft-17／FE0.16-draft-16不变。依据用户已确认的[独立迭代](../../iterations/pending/v2.0/WALL-E.仓库首次登记原操作归属细化_V_2.0.md)：原事务预留Repository ID及真实Operation／Step，首次登记统一202。无占位仓库／Task，原202不改写。

新增repository_acceptance.py、repository_registration.py、repository_observation_publish.py；共享command_registry／command_receipts／identifiers及Schema guard／索引同步。登记capture只接原RepositoryMetadataLease；观察capture要求原metadata＋WorktreeHeadLease。所有Git／Native读取在写事务外。登记完整仓库、原两步骤及原操作成功同短事务；观察记录／ID及原步骤／操作同事务。登记验证阶段不把原路径／指纹作为result_ref，SAVE_FACT只存真实repository_id。内部capture是程序数据，不是客户端证明或完整Guard派发器。

## 环境与执行

.venv Python3.13.5，SQLite3.54.1由tools/python-v20.py先激活，Ruff0.17.3；普通非提升隔离环境。tools.quality_gate.environment＋tools/quality_python.py，-q -p no:cacheprovider --tb=short，TemporaryDirectory内--basetemp；禁止正常业务库／本地凭据及外网，Native仅临时仓库／私有目录及自有Job，无模型／计数调用。源码通过同目录temp＋fsync＋原字节复核＋os.replace保存。

- 原观察生产初轮：test_repository_observation_publish.py、test_repository_observations.py及test_v20_git_metadata_command.py::test_fixed_metadata_commands_use_real_asuser_job_capture_and_original_ref_cohort，30通过、1警告，151.48秒。
- 接收／原回执／ID分配：test_repository_acceptance.py、test_v20_command_receipts.py、test_identifiers.py，37通过、5子场景、1警告，13.16秒。首轮新fixture误将已经acquire的ProcessLock再作为context进入，19通过／19设置与清理错误；修正为由context唯一持有，进程退出后临时目录按owner清理，生产代码不涉及该错误。
- 中间组合：以上接收／发布／观察、test_v20_schema_construction.py、test_v20_schema_release.py、test_v20_published_schema.py及真实两格式Native组合，共74通过、26子场景、1警告，103.47秒。此后登记发布收敛为原VALIDATE与SAVE_FACT／仓库同短事务，不留原metadata作为result_ref；最终受影响专项见下项，不能把中间结果冒充最终。
- 最终登记发布／接收：test_repository_registration.py＋test_repository_acceptance.py，28通过、1警告，11.56秒。包含原预留唯一索引精确UNIQUE拒绝（独立PROCESSING claim），以及最终短事务失败后步骤仍为原PENDING／RUNNING、原记录和原202协调。
- Schema资源：tools/python-v20.py tools/schema-v20-release.py --release-id db20-r13，实际发布成功。manifest SHA256 1d4f3f06d385d5669e4482ada0534509b7945c9ff756b82cf7e115d2813ed8a2；r1—r13保留，无正常库升级。
- 静态检查时点：213个backend/app文件格式通过，新增登记模块及共享receipt lint通过；最终214文件格式、10个受影响模块lint及git diff --check通过。

## 实际覆盖及限制

原键并发仅一操作与预留ID、异键独立、改体冲突、先关闭不分配、分配后异常全部回滚、提交确认丢失后原202／ID不变、容量用尽确定拒绝、refresh真实仓库归属／不可变404；SQL原claim／原键／正文／状态／sequence／动作及缺字段NULL不能绕过。唯一预留索引不允许第二原操作认领同预留。

登记完整记录／两步骤／原操作原子提交、无来源重读重放、取消／未启动拒绝、原选择与canonical路径／格式／指纹校验、同common目录冲突不覆盖原仓库；观察发布原两ID与仓库／步骤绑定、原API71读取、异常回滚及未知提交协调。两格式Native实际原句柄捕获，不以SQL夹具冒充Native调用。

仍无完整REGISTER／REFRESH生产调度、真实Guard认证Pipe／LPAC-WFP部署、仓库业务HTTP及设置页面。本批新增HTTP为0，仍18条；不得将内部组件当全流程验收。真实供应方、正常服务／数据、前端浏览器未执行。原目录runtime_admitted=false、ready=false保持。

## 原操作查询及前端接入（后续单元）

新增repository_operations.py及实际GET /api/v1/code-operations/{id}：当前只实现REGISTER_REPOSITORY／REFRESH_REPOSITORY资源分支；其他家族明确CONFIG_NOT_READY，不投影任意JSON。原操作／固定步骤／原202回执／实际完成对象在同读事务关联。登记资源未创建时仍可读原PENDING／RUNNING／FAILED；任务owner、内部绝对路径及Guard／Job私有身份不外发，固定输入仅name或repository_id，原字段及null保留；成功必须原两步骤及原保存对象存在。GET无Git／写入／刷新。

- 初轮5文件组合42通过／6失败，91.52秒。查询错误假定原幂等表有operation_id列；实际原关联由不可变success_result_json派生。修为核对原202 DTO中的ID，不新增第二关联列。停收测试使用了不存在的app状态，修为实际worker.accepting。
- 修后test_repository_operations.py，12通过、1警告，46.70秒。原状态、失败200、秘密投影、坏引用503、非法ID／查询／请求头及停收覆盖；随后完整REFRESH发布→API17→API71原引用组合及正常启动回归，test_repository_operations.py＋test_v20_startup.py最终15通过、1警告，67.55秒；含既有非空151不自动升级、实际默认200启动及真实__main__先激活SQLite。
- service路由改变后实际发布db20-r14，manifest SHA256 cf8f49219ce687f7434f935fc65e00266578a4183af9639e561777a89d77f34c；SQL内容沿r13，来源清单更新，正常库未动。
- 前端code-repository-operations.ts、code-repository-commands.ts／WalleApi及共享commandReceipt接入。C01／C02仅202及4字段、PENDING原回执；C02核对路径资源；原键冻结／恢复复用，拒绝201、跨操作和伪造Task归属。原操作只读、深冻结、严格原ID／无分页与安全字段验证；UI未新增，业务POST后端尚未接。
- 前端首轮新专项8通过／1失败，检查错误给restoreCodeCommand传入数组，实际函数接受单个binding；改测试按既有入口，生产共享恢复流程不改。修后全套529通过，6.09秒；临时Vite构建1.02秒通过（既有大chunk提示），输出自动清理。随后增加C01／C02回执不能获得Task owner的约束，最终全套529通过3.15秒，strict／npm run format:check通过。
- 本单元新增1条实际只读HTTP，当前19条；API17其余操作家族、C01／C02生产HTTP及原生调度、全部设置UI和浏览器端到端仍待做。不得将前端Mock或SQL准备状态称完整Guard业务验收。

最终共享前端归属修正后临时构建再次通过，目录自动清理；无活动检查或待取回执。
