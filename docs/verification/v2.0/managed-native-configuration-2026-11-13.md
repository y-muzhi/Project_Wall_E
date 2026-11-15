# 受管目录编译及活动原生配置（2026-11-13）

## 实际时段、基线及授权

用户指出前一批仅约13分钟，香港12:37:38继续补足剩余约1小时47分钟；本记录随实际检查更新，未把完成单元当暂停。当前master／28a7c9e13c73a9d386081a6dd894244b51746a45，保留既有及其他任务改动；不提交推送。BE0.17-draft-17／FE0.16-draft-16及Schema200 db20-r44／SQLite3.54.1不变。正式设计摘要沿用[前批记录](native-permission-origin-2026-11-13.md)，本批独立迭代不合入设计。

当前实施和必要隔离离线检查已授权；无真实模型／计数，无用户数据库、正文或Git目标写入，无SYSTEM／WFP安装，无用户服务启停。原子源码及格式结果用完整内存→同目录临时文件→flush/fsync/close→原字节CAS→os.replace，失败清理临时文件并保留原源码。

## 实际交付及不变量

- [目录与编译迭代](../../iterations/pending/v2.0/WALL-E.受管目录引用与原生权限编译迭代V1_V_2.0.md)：READ20-WORKSPACE-1／READ20-BASIS-1两个抽象引用、冻结资源及code20-r3目录。旧r1／r2原字节保留；r3 manifest schema2绑定资源摘要及完整两项覆盖，ready=false仍需Q20-CONFIG／Q20-WINDOWS。
- task_native_policy.py严格profile／授权及真实NTFS身份编译，原生deny-all后仅workspace read/edit及可选basis只读；无命令、网络、搜索工具。TaskInstanceDriver在原Guard准备时固定basis身份，create_session读取同组当前业务输入，编译前后复核来源；只有原START第五步允许BOUND_PENDING_APPLY，继任只认EFFECTIVE。
- [原生C39迭代](../../iterations/pending/v2.0/WALL-E.受管读取范围原生配置应用迭代V1_V_2.0.md)：保留原四步与表，读取范围只在原成功START授权内收紧／恢复；新批准授权在接受前固定，不凭客户端permission扩大。阶段2形成真实配置／provider／session／Guard／NTFS观察；独立持久阶段3的nonce、旧组／目标摘要及创建／前驱来源。首次独占发布者才可PATCH，未知或原意图缺失只读恢复，不重发。
- 阶段4再次真实读组后才原事务APPLIED／EFFECTIVE。已采用原生链从完整业务成功链读取，普通后续消息／捕获／问题等依据原创建加已采用前驱；pending／失败／未知原生ACK不能成为普通执行基准。连续显式变更含两次原生应用，仍一份原创建会话。
- 源码TaskNativeActions新增显式permission_history及expected_session_policy。TaskInstanceDriver新prepare_native_configuration／apply_native_configuration与原scheduler接通；普通CONTROL_ONLY仍原路径。原生目标admission在准备／外发前及采用前均核对，遗失后不派发，恢复不能补发。
- 前端严格解码两种目录项、目录显示及授权范围业务名称、原配置流程说明；已有原请求／原进度恢复按钮复用，无新端点、按钮样式或自动继续。

## 固定上游源码核对

OpenCode固定提交810c0eba1a7348036f8bdf61e6632d0c36c6876c，经GitHub连接器读取tool/read.ts／edit.ts／write.ts／external-directory.ts／grep.ts／glob.ts／apply_patch.ts、permission/index.ts及core wildcard；permission/next.ts实际404，不作为证据。registry.ts Git blob9167cb3ea6bc5c8dd075f0f8271adbdec6074b12仅对特定gpt-* modelID选择apply_patch；当前walle-code／walle-compaction固定id不满足。生产checked_coding_configuration及原启动配置摘要拒绝更换；运行包不开放plugin／mcp／experimental。

apply_patch移动目标未进入最终edit模式列表，不能把本规则泛化为它的完整目标保护。本批工具集合不含该工具；将来改模型id或工具集必须重新评审。grep／glob检查搜索文本而非路径，故不开放。Python规则求值端口只是源代码衍生离线证据，不是正式原生执行器证明。

## 环境、命令及阶段结果

Python使用项目.venv及锁定Ruff。涉及数据库的专项必须先经tools/python-v20.py激活固定SQLite，再进入tools/quality_python.py离线护栏；环境来自tools.quality_gate.environment，TemporaryDirectory独占，pytest -p no:cacheprovider及显式--basetemp。stdout/stderr内存读取，所有输出只临时存在，结束finally清理。浏览器用已安装Playwright CLI、真实Chrome及OwnedJob，临时构建前端与FastAPI／Schema200数据库；Guard／supplier仍明确夹具。

| 范围及实际命令入口 | 本轮观察结果 | 解释及边界 |
| --- | --- | --- |
| python-v20.py quality_python.py test_configuration_options.py test_authorizations.py test_execution_profile_versions.py | 91项通过，243.39秒 | 首次未经过固定bootstrap导致49个setup错误，修正命令后通过；不增加产品SQLite回退 |
| test_task_native_policy.py | 初版66项通过，1.35秒；末次扩展85项随255项联合通过 | 真实NTFS及源代码衍生规则求值，不是原生运行效果 |
| test_task_native_policy_source.py | 11项通过，110.65秒 | Schema200原START／当前同组／STOP；不用用户库 |
| test_v20_managed_native_policy.py | 8项通过，3.90秒 | 原create_session实际编译→HTTP；首次6失败为夹具错误假设丢POST后不会立即GET恢复，修正故障注入同时丢首次列表GET |
| test_v20_native_permission_application.py | 扩展后101项通过，28.03秒 | 新增已采用历史后真实消息入口及历史意图／ACK缺失拒绝；原267项见前批，不相加 |
| test_task_configuration_control.py test_task_live_configuration.py test_task_start_instance.py | 44项通过，555.28秒 | 原CONTROL_ONLY／START关联，随后新增的检查仅在native分支 |
| test_task_native_configuration.py test_v20_native_configuration_flow.py及浏览器2项联合 | 17项后端通过、2项浏览器失败，485.35秒 | 原17项初次有3个错误期待：越界真实403、STOP接受不等于已核实终止、停止栅栏advance返回false；修正测试按原停止完成后C39 CANCELLED核对，不放宽产品 |
| 原生C39浏览器2项 | 最终2项通过，120.35秒 | 首次CLI使用30秒idle，执行实际NTFS／SQL阶段时浏览器上下文被关闭；改仅native-read使用240秒idle／180秒命令，进程220秒硬限及finally清理 |
| 前端v20-configuration-options.test.mjs | 8项通过 | 从实际r3资源解码，恶意scope／ready等拒绝 |
| npm --prefix frontend run typecheck；format:check | 已通过 | strict／未用参数和锁定Prettier，不替代实际交互 |
| verify-v20-settings-browser.mjs实际Chrome | 已通过，360／1280 | r3加载、空、失败、重试、未准入显示及原设置流程；OwnedJob及输出已清理 |
| Ruff生产检查 | 末次选中26生产／测试／工具lint通过、500文件格式通过 | 包括489生产、10专项与1工具；node --check工具通过 |

阶段结果存在重叠，不相加成独立通过总数。原生HTTP是独立loopback夹具，真实NTFS／API／DB／Chrome不能替代供应方、正式OpenCode进程或SYSTEM／WFP权限证明。

## 尚未覆盖

正式SYSTEM／LPAC／WFP和原生执行器同组准入、真实模型、完整命令／网络／搜索授权、完整产品从CHECK_DRIVER到Git交付仍未由本批证明。目录元数据ready=false保持，不以离线通过放开正式准入。不自动合并独立迭代或更新用户服务。8000／5173最近12:33均无监听，未推断退出原因，本批不重新启动。

## 末次结果及源码摘要

- 末次编译／来源／创建／原生权限／控制五文件255项165.61秒通过；分解85＋11＋8＋101＋50。之后新加模型别名拒绝由ACK／会话／定向控制125项25.73秒通过（含控制6项），与255重叠，不相加。
- 原生C39真实驱动扩展9项382.36秒通过：第三步已预留未发布意图中断保持UNKNOWN／0 PATCH，恢复仍不发送；最终配置／权限／basis身份漂移保持旧业务授权，恢复原组后仅GET。混合CONTROL_ONLY夹在两次native之间另1项119.20秒通过，普通配置不加入原生历史，两次PATCH仍同一原创建会话。随后新增实际PATCH后预算并发1项53.75秒通过：旧第三步保持RUNNING，新预算0.200000保留，原步骤后续仅GET并采用，无第二PATCH。
- 实际Chrome原生C39两场景最终2项120.35秒通过，旧30秒idle问题及修正保留在上表；真实SQL／HTTP／浏览器，OS及supplier仍是具名夹具。
- Ruff选中26文件lint通过，489生产＋10专项＋1工具共500文件格式通过；git diff --check通过（仅既有CRLF提示），清理dry-run JSON=0／screenshots=0。
- 同轮后续完成[离线运行包清单准备](offline-opencode-manifest-preparation-2026-11-13.md)，只准备元数据，不提升正式运行状态。

下表是本轮末次原字节摘要；历史验证的旧摘要不改写。

| 文件 | SHA256 |
| --- | --- |
| backend/app/infrastructure/managed_read_scopes.py | d8488907c5b5d328dac2032c8cbb381a90917f9d53e5f165f26be3a7f01de6c6 |
| backend/app/infrastructure/code_configuration_catalog.py | e7caa5e8b52c830f4910e396abc61f15a34dc85f36318b0a70ec185292b95f33 |
| backend/app/infrastructure/code_catalogue_admission.py | 9da43b8a1bab7ceffef64ba5defab337d4ad32610b60ed6e5ef2ac4c7c953a87 |
| backend/app/code_tasks/task_native_policy.py | 6043bbb947024488e111761b454d199a94e68b651f0469f316ed04987f639d29 |
| backend/app/code_tasks/task_native_actions.py | cb2b43c860e3eacb1be0818ba3a04a075a4384cd0b34a2bffa255ed6d5c6f5d1 |
| backend/app/code_tasks/task_instance_driver.py | f7d72fd7bd962763da179d4caeee2dccf2b4c979697fec3d8e00f5379d327a8f |
| backend/app/code_tasks/task_configuration_native.py | 1a4cde570b9a0cf8f4190b512b6596aaa179fa471a5c0af3e8b54ba6bbb85311 |
| backend/app/code_tasks/task_configuration_effective.py | f11d3ef0592eb8d615d149ddd6b3a0ce0e3e794d830cf1a568a6902f0d29fc01 |
| backend/app/code_tasks/task_configuration_apply.py | 246400036de9e148096919fa49b18383b4f169e4ec3685393fff88bfe4fc33e2 |
| backend/app/code_tasks/task_configuration_live_records.py | b5ae15e73b6ae02c3a69426dabfd615e2b3b1b6354024f95d9c49f93032585c9 |
| backend/app/code_tasks/task_configuration_control.py | a5504f61cdecc93dc5eafeff7df47f07895c3362008e70f930e45deb768e52d2 |
| backend/app/code_tasks/task_live_configuration.py | f7278d73c13025b469e3208eec57f09ea2161fe758b622c37661b77ec55a9381 |
| backend/app/code_tasks/repository_registration_worker.py | 436de0988138054451c0889849f2fd4f0a137091845afe38fcb213b0cff0c60a |
| backend/app/infrastructure/opencode_runtime_bundle.py | 43fdc93b3b231638a88316fcd23fd88300a2f09d4c95421f02648ec598df8164 |
| backend/app/infrastructure/opencode_runtime_preparation.py | 358d6e15bf056d255a202e10859a74d405b53e9ad95b7cea9cc65abbe3d02b5a |
| backend/tests/code_tasks/test_configuration_options.py | f22b38b5b5ee8b4bd957256acd30d4b9de1eb81531e9747d5b1d8bb93e79c49e |
| backend/tests/code_tasks/test_task_native_policy.py | ab7633809ef206e9210f61dfb32b628def8fb2a1f9b95f20f4fe20237c0eed1e |
| backend/tests/code_tasks/test_task_native_policy_source.py | 91a1ad32e7f04ae062ca937f0b548967328700d3b5171bb75a091a41c80285af |
| backend/tests/code_tasks/test_task_native_configuration.py | 68fb553af111bec2a57bb7c941983970f56778c3760a3121320391fb042c8c80 |
| backend/tests/infrastructure/test_v20_managed_native_policy.py | bde773ecd907d44db0f39b38ef68913463d36950ac51d75e6292e7eb68e5436c |
| backend/tests/infrastructure/test_v20_native_permission_application.py | e37305bb39d63c78f5d90a59ac8612444beff3f60e3bb200d701b53770a76a75 |
| backend/tests/infrastructure/test_v20_opencode_instance_control.py | 099c4ddec0e22167dcf7fad3a44f9d2bb0b46a75b36be285af0066766e86cf65 |
| backend/tests/infrastructure/test_v20_native_configuration_flow.py | 9187518bc263d86bd5de418e0ea5dfd07115dd0aa6fec29b4c0372501bc6292c |
| backend/tests/infrastructure/test_v20_native_configuration_browser.py | b5856586bc71b6b9215355f1f803ad35c1fcaff1eb2466bf821c03fd49867c82 |
| backend/tests/infrastructure/test_v20_opencode_runtime_preparation.py | 0a012f05bc7b3c10bfb2557524f7ee68f368e2573a3cbaca5f0d6c2d89836ffa |
| frontend/src/api/code-configuration-options.ts | 09b7bf02c2d33adf3218cd552215cb970c301d125147462545912a2e4af9f745 |
| frontend/src/code-tasks/settings/configuration-catalog.tsx | 7b16cba63b15b59bb920ad940c611804fd9d2e8baadb2a49b9e16db94969a3c7 |
| frontend/src/code-tasks/settings/authorization-view.tsx | 1dc8181c5378d8defcc961dd74fcfa327983243d206d184fc22a4db60bc44b19 |
| frontend/src/code-tasks/configuration-control.tsx | a1ec2bf29b078bb929889e3b6804e53a923250840be6fd4f480b2c051ec08ae0 |
| frontend/tests/v20-configuration-options.test.mjs | 03d54c3b446ce2c1ddc090865fab80eee7907595da08a1dbcb8a30671a2bef88 |
| tools/verify-v20-settings-browser.mjs | 1381e89dfcd21bf6794bd850f326d93b799e814fdd460f95d83f42c5cd00c0eb |
| tools/verify-v20-live-control-http.mjs | bc05556a027f66343fe1ba54d9e9a6901b691b6334210b599dcf59108db0f2f7 |
| tools/prepare-opencode-runtime.py | 89a07eed5f3a6d9ca3e5612386b5e578531877dec62f0d7e5eff1f55bc37ef70 |
| backend/resources/code/managed-scopes/managed-read-1.json | 893ed2a7a4276d843df97041e201f6fa5e64c3841eaea877e927b0baa34bd097 |
| backend/resources/code/code20-r3/manifest.json | a009afe7dd78664658ae4d6d45263053c15d25ce5ad661262ab7932b89432127 |
| backend/resources/code/code20-r3/options.json | 9d944afc773ac1f9acd8d61483a0eb7abdfbdf062bc86d6e520902b26f85c7e6 |


香港14:20收集完末次在途结果：本批全部检查均已结束，无未知操作／检查结果。文档收口继续；最终时段见实现进度。

末次文档／现场静态核对：486个相对链接无断链，40条本轮源码摘要一致；专属临时根0，Git折叠432条，master／HEAD不变。正式BE／FE摘要与原基线一致。最终人工源码审阅确认原_continuation_guard仍核对原receipt／process身份、STOP封闭、完整Job及唯一原进程成员；没有把CaptureTurnEvidence中的1当独立OS证明。

香港14:23生产调用方静态核对：rg搜索backend/app及tools未发现RegistrationInstallation或TaskRuntimeBundleDeployment的实际生产构造，仅service.create_app提供可选注入；明确是下一首个待实现调用方，不把测试注入或准备工具当正式启动组装。下一步及所需文件见实现进度，当前默认未部署继续不可执行。

本轮时段最终记录：香港12:37:38至14:24:55，接续实际约107.3分钟，连同上一批约13分钟累计约两小时。全部检查已收集，当前断点／计划／需求映射／三个本批pending及离线准备说明已同步，无在途检查或半成品函数；版本目标未完成项仍按映射及下一首个部署组装单元接续。
