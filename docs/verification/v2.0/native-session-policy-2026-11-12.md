# 原生会话策略基准及发送前核对（2026-11-12）

香港20:25／UTC12:25:44开始约半小时工作量，后收到“继续推进”沿同任务接续；仅以命令实际结果／耗时作证，不推断聊天间隔等于已运行检查。master／28a7c9e13c73a9d386081a6dd894244b51746a45，Git起点423条。BE 0.17-draft-17／FE 0.16-draft-16 DRAFT摘要与当前断点匹配，Schema200 db20-r44／SQLite3.54.1不改。先保存[独立pending](../../iterations/pending/v2.0/WALL-E.原生会话策略观察基准迭代V1_V_2.0.md)。

## 实际实现及不变量

TaskNativeActions.observe_session在GET后、补ACK／返回前核对原创建的title／agent／model／完整有序permission，metadata精确关联。现阶段没有原生C39已验证应用，基准仍原创建；之后完整C39接入必须先推导合法应用后的期望策略，不把GET自证或未验证PATCH当已采用。

初始／继任消息及TaskInstanceDriver最终继续派发，均在POST前复核原会话。继续入口先完整冻结payload与messageID，再GET、检查点、queue_continuation及POST。策略漂移／停止／错msgID时零queue／POST；载荷别名在新增检查点被调用者修改不改变实际wire。失败沿原操作未知／只读核对约束，不自动重POST，不新增NOT_SENT或自动恢复结论。

完整正回执字节容量在GET／意图／POST前预检：session以ses_+96的最长合法ID预留，initial以固定msgID计；不是磁盘容量或断电证明。permission已有完整回执预检保持。

## 命令、实际结果及失败修复

隔离方式沿tools.quality_gate.environment清除真实凭据／代理，WALLE_TEST_CONTROLLER_POSITIVE=1；TemporaryDirectory(prefix=walle-v20-native-ack-)包裹tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short --basetemp <自有目录>/pytest <目标>。已结束均OWNED_TEMP_CLEANED，只留Markdown，无JSON报告／截图／原始日志。

- 首轮151项26.50秒通过：新test_v20_native_session_policy.py 8个有ACK／丢ACK字段漂移场景，加原native_acknowledgement／opencode_instance_control／native_permission_application三文件。
- 增加生产入口及最终派发后，99349七文件192项170.66秒通过：上述4文件＋backend/tests/code_tasks/test_task_resume.py、test_task_role_chain.py、test_task_repairs.py。生产入口测试实际TaskInstanceDriver复用loopback控制，Guard读回和live owner显式stub，不作真实OS同组证据。
- 追加初始消息真实GET后，3493在158项通过后失败21.95秒：旧容量边界要求失败前零外部访问，但新GET发生在包络检查前。保留断言，修复session／initial完整正回执预检顺序，新增“intent可存但ACK超界”两个场景。
- 最终23822四文件171项23.90秒通过（新28项与原143），包括实际loopback／NTFS、拒绝漂移且不补ACK、合法字段恢复不重POST、生产继续／捕获／修复预检、最终派发冻结／STOP、初始／继任GET及容量早拒绝。自有目录清理。192项导入早于末次GET／容量变更，不改写为最终代码全量通过；覆盖重叠不相加。
- 最终2生产及新专项lint、backend/app 484文件格式、git diff --check通过（既有application-router.test.mjs换行提示保留）。前端src、Schema、资源及正式设计未改，不重跑无新增风险的前端strict／浏览器。

## 最终源码状态

| 源码 | 原字节SHA256 |
| --- | --- |
| backend/app/code_tasks/task_native_actions.py | 53c4c376f28bd01082be4a28839e943586b8e3119184aac4a0291e1b6f4807e0 |
| backend/app/code_tasks/task_instance_driver.py | 3f3dbb2d5311a1a1086ef5e8c49d49b0f3fb3c2c7573301b3e8e74ddf77412d0 |
| backend/tests/infrastructure/test_v20_native_session_policy.py | af4e1ba45d964cd6c3c52c916bfeb8a91fffae13ef2e30d19fb0c2a12614f72c |

完整原生授权编译／OS同组／独立第三步公开状态、config/providers的完整每轮组核对、正式CHECK_DRIVER／SYSTEM／WFP、真实供应方及产品完整交付仍未完成。本批不更新用户服务／业务库／Git目标，不真实模型／计数、不提交推送。旧捕获首失败原因未唯一确定，不以本批替代该分支调查。

## 收尾核对（香港22:03）

三个最终源码原字节摘要均与上表一致；本轮七份关联文档相对链接无缺失。Git HEAD未变、工作区424条；git diff --check通过，仅保留既有前端测试CRLF提示。原子保存临时文件零，本轮walle-v20-native-ack-*目录零，专属quality_python.py进程零，8000／5173／5174无监听。tools/cleanup-test-artifacts.py --dry-run实际结果JSON=0、screenshots=0，无需删除；不删除业务数据。
