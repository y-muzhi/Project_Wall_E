# 原生回执前置关联与恢复（2026-11-12）

香港19:24（UTC11:24:17）接续约半小时。master／28a7c9e13c73a9d386081a6dd894244b51746a45，Git折叠422条，保留其他改动。BE 0.17-draft-17／FE 0.16-draft-16及Schema200 db20-r44保持；正式摘要沿当前断点，未合并。19:33正常8000／5173／5174无监听，不启停用户服务、不真实模型／计数、不SYSTEM／WFP、不提交推送。

先保存[独立pending](../../iterations/pending/v2.0/WALL-E.原生回执关联与恢复前校验迭代V1_V_2.0.md)。TaskNativeActions新增完整ACK前置关联：scope／action／完整input精确JSON相等，按session／initial／permission检查完整result；initial accepted必须true，permission须原session及有序before+rules。observe_session、send_initial、observe_initial及observe_permission在外部访问前使用。初始消息丢ACK时也须结构合法及原创建ACK绑定，不能以当前GET自证目标。无ACK只读原身份恢复、有合法ACK仍读真实事实；不自动重POST／PATCH。

## 检查方式与实际结果

均经tools.quality_gate.environment清除真实凭据／代理，WALLE_TEST_CONTROLLER_POSITIVE=1；独占TemporaryDirectory(prefix=walle-v20-native-ack-)与tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short --basetemp <自有目录>/pytest。已结束运行均输出OWNED_TEMP_CLEANED。仅留Markdown，不保存JSON报告、截图或原始日志。

- 新test_v20_native_acknowledgement.py首运行失败1.88秒：错误引用测试模块不存在的strict_json_object，生产路径未执行新断言。修正脚本的格式化副本失败，原文件保留；工具编排错误继续重跑旧文件，同原因1.74秒失败。随后完整内容在内存构造、通过Ruff后原子保存，工具改为检查编辑exit_code再启动，避免重复旧失败。
- 初版三文件专项127通过／19.19秒。追加初始消息丢ACK后的目标绑定／畸形意图零GET分支后，最终三个文件130通过／23.69秒：backend/tests/infrastructure/test_v20_native_acknowledgement.py、test_v20_opencode_instance_control.py、test_v20_native_permission_application.py。新27场景用读取边界注入冲突，不篡改不可变私有文件；原NTFS记录、实际loopback HTTP、丢回执、STOP、独立进程只读恢复沿原专项覆盖。恢复合法读取后继续同原事实。
- backend/app 484文件格式、本轮生产及新专项lint通过。无前端src或公开协议形态变更，不把旧浏览器／strict结果当本轮证据。
- 启动、角色、修复、继续及私有修复文件五文件相关回归58068：42通过／274.52秒，临时目录清理。目标为backend/tests/code_tasks/test_task_start_session.py、test_task_role_chain.py、test_task_repairs.py、test_task_resume.py及backend/tests/infrastructure/test_v20_task_repair_file.py。

## 未覆盖

本批修复原动作真正使用的恢复／发送边界，但不等于通用C39权限编译或系统同组准入。NativeCodingPolicy固定授权／资源编译、第三步独立RUNNING／UNKNOWN及前后端解码、正式CHECK_DRIVER／SYSTEM／WFP、真实供应方与完整产品交付仍保持未完成。旧首次捕获失败仍未唯一归因，本批不声称回执修复解决该故障。


## 最终追加及当前结果

原创建ACK丢失时先完整校验session input／metadata，原session与初始消息intent畸形JSON统一为TaskExecutionError；planned信封及完整message input也在取字段前校验。目标不匹配／非法计划不发GET、不新建意图或替代消息ID。新增真实NTFS测试在没有ACK的原槽一次发布错绑回执、重开原动作后拒绝外部访问，错误记录原字节保持，不默默覆盖；这与此前读取注入分别说明。

40203三文件141项22.68秒通过；最后补齐session／initial原意图坏JSON两场景后，60029最终三文件143项23.28秒通过（新40场景及原103场景），均清理自有临时目录。完整ACK、原创建／初始消息、计划及真实私有记录恢复各自然单元完成。42调用方回归导入早于末次计划／原创建预检，合法载荷结构不变；最新143项含实际TaskInstanceDriver／HTTP及新增失败边界，不改写旧轮为最终代码全量验收。没有待取结果或半成品函数。

最终生产task_native_actions.py SHA256 a9e299b38deceb398e694af154e73ab0a49db9429b3d4f0ceae40b4dd33703aa；新增test_v20_native_acknowledgement.py SHA256 fb6d3683925d95795eb8cfa4a95d5672759529042ccc5bc84ea2f30050cc4d1f。按文件原字节直接SHA256，不跨集合累计通过数。最终两文件lint与backend/app 484文件格式通过；源码全部原子保存，格式失败时目标保持。未修改前端、正式设计、Schema、配置／资源或业务数据。


## 19:52收尾

源码原字节SHA再次匹配，7份关联文档链接缺失0、唯一当前断点1处，新2条业务映射均6列。原子临时文件0，自有quality_python进程／walle-v20-native-ack目录0，cleanup-test-artifacts.py --dry-run为JSON=0／screenshots=0。19:50正常服务三端口无监听；HEAD保持，Git折叠由422至423，新增独立test_v20_native_acknowledgement.py。正式前后端SHA保持，无普通业务库、用户服务或Git目标更新，无真实模型／计数及提交推送。检查均结束，无待取结果。
