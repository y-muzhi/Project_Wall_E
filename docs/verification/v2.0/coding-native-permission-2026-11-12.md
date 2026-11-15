# Coding原生权限及持久外发专项（2026-11-12）

香港11:01启动，master／28a7c9e13c73a9d386081a6dd894244b51746a45，保留原工作区。BE 0.17-draft-17 SHA256 1A8D277F25DE570CE72E74A73FF763BF73F622FCF94B61F0820B78A1A5C6FD37；FE 0.16-draft-16 SHA256 38557CEE854697044AB7DABA30F694738429BE1235264A153851E8FC808CF3A7，未修改设计。原生netstat核对8000／5173／5174无监听；不启停正常服务，不改正常数据、SYSTEM／WFP或真实供应方，不提交推送。

## 环境及命令

.venv Python3.13.5、固定SQLite3.54.1；tools.quality_gate.environment构造无秘密配置／外网代理的隔离环境，WALLE_TEST_CONTROLLER_POSITIVE=1。TemporaryDirectory独占，tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short --basetemp <自有临时目录> <以下目标>。所有已完成运行均退出后删除自有目录，只留Markdown，不留JSON／截图／原始日志。

## 固定源码依据

[session处理器](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts)先读原会话，再将permission交给合并函数，其他字段只有明确提供时修改；[Permission源码](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/permission/index.ts)merge为有序拼接，evaluate取最后匹配，缺匹配才ask。故显式reset必须作为新增规则首项，而最终读回应是旧序列加新序列。最初按旧next.ts路径读取404，已定位固定提交index.ts；无依赖升级。

本层不实现通用Wildcard解释器，也不从几个样本推导全部权限等价。需要固定组编译和OS边界的C39采用尚未开放。

## 已执行及实际结果

- 改动前原test_v20_opencode_instance_control.py：50通过，7.77秒。
- 原生权限首轮1失败／1.38秒：新permission动作未纳入PrivateRecordAppend允许命名。未外发PATCH，临时目录清理；已仅扩展该动作intent／ack白名单，未放宽任意文件名。
- 权限、旧协议及私有记录组合79通过／9.27秒，含丢回复后重建原动作只读恢复、会话／agent／model／metadata／title／规则漂移、明确reset、非法规则、STOP后不发PATCH。
- 新并发及容量／调用者别名专项20通过／3.88秒：两个同原身份对象在读取意图后竞争，真实NTFS不覆盖发布只允许一次创建、一次初始消息或一次权限PATCH。输入别名改变不能改原字节。
- 最新三个原生／私有记录文件92通过／10.29秒，含完整载荷前置校验、非法输入无意图／无HTTP及创建／消息快照。
- 原生、启动会话、继任会话、角色链、修复六文件114通过／133.13秒；此运行在完整载荷前置校验保存前已加载，作为并发发布改动的关联证据，后续最新代码需另补相关回归。
- 本批三个生产模块及新测试文件Ruff lint通过。新测试最初沿用旧fixture导入方式触发F811，已改模块引用显式登记fixture，不屏蔽规则或删除夹具。
- 原PROJECT_CHECK_HANDOFF真实Guard联合正在执行，未提前记通过。真实NTFS／固定Git／SQLite／认证管道／Job与项目命令，原生消息为离线夹具，不替代真实OpenCode／供应方或正式SYSTEM／WFP。

## 当前边界

三个生产模块：infrastructure/opencode_instance_control.py、infrastructure/windows_private_record.py、code_tasks/task_native_actions.py；旧本机HTTP夹具及新增test_v20_native_permission_application.py。源码均同目录临时文件flush／fsync、原字节比较、os.replace，保持原编码／换行及模式。

权限PATCH／持久恢复基础层已专项验证，完整C39字段放开／原授权到NativeCodingPolicy编译／OS同组证明仍未完成，不冒充完整运行中权限配置。当前生产已受影响的原创建／消息共享发布与前置校验另做关联回归。未改Schema、正式资源或前端交互。


## 11:36 接续保存

- 最新角色／修复／启动／C39七文件147通过／423.85秒，含完整载荷前置校验版本；此后仅增加原记录容量和恢复输入校验，未改变原调用正常载荷。对应新增边界由下方107项补验。
- 新发布结果未知、ACK保存确认失败和非法规则专项34通过／5.22秒。独立Python进程复用原控制客户端及NTFS私有包，凭据只临时stdin传递，仅GET成功补回原ACK：1通过／2.29秒。该项不是生产后端全量重启／进程锁接管；首轮端点误按dict读取而实际为tuple，1失败／1.38秒，已按原端点读取，不改产品。
- 原记录容量／严格恢复输入加入后，三个本机协议／私有记录文件107通过／13.22秒。容量夹具首轮将共享读取上限缩到32字节，先被原会话ACK读取正确拒绝，42通过1失败／7.50秒；现保留原ACK读取容量，再用较大的明确消息测试新记录上限，不放宽产品限额。
- PROJECT_CHECK_HANDOFF 1通过／828.93秒：原角色、修复、新候选、自检、配置、发布及收尾真实Windows／NTFS／SQLite／认证Guard链完成。原生模型／会话为离线夹具，不把本项当新增permission PATCH真实包验证；运行期间新增权限记录容量／恢复校验的独立边界由107项实际HTTP及NTFS证明。
- C39原生提议门槛2通过／22.32秒：模型范围收紧、显式登记读取范围变化均仍CONFIG_NOT_READY，原Task版本／旧授权不变，无新操作，提议保持APPROVED_UNBOUND。读取资源登记为隔离目录夹具，不是OS安装；首轮误取无命令fixture的首项失败（1通过1失败／22.44秒），改为实际存在的两种提议范围，不把无效命令当准入证据。
- 本批生产和新原生测试文件lint、481个生产文件格式均通过。单独扩大旧HTTP大测试文件lint时发现既有第717行未用control变量，未为本批改写该旧行，不称旧文件整份lint全过。新C39测试一条无效noqa已移除。最初格式命令尾部误带独立“./”使整体退出1；其格式部分通过，之后已用独立正确命令再次检查481文件通过。
- 固定版本[主循环](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/prompt.ts)进入循环前读取session；[工具上下文](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/tools.ts)按agent在前、session在后组合权限。本轮不改执行中的旧循环。工具源码首次网络读取失败，后按相同固定提交成功读取；不以网络失败猜测规则。


## 11:44 原来源窗口关联修正

扩大到原继续、实例、配置准备和原生静止时，16通过1失败／159.39秒。失败来自旧test_model_preflight_reads_only_active_current_sqlite_window：它在实例准备后手工插入ACTIVE会话、设置Task RUNNING及授权EFFECTIVE，却未完成原START CREATE_SESSION来源，仍期待模型窗口有效。现行effective_control_application正确拒绝缺失原创建证明；不是本轮新权限方法可绕过的条件。

未改该生产保护。正向夹具改经advance_start_instance及原advance_start_session两步完成真实SQL原来源；另保留原手工ACTIVE／EFFECTIVE构造为缺证明必须StorageUnavailable的负例。两项25.45秒通过，覆盖当前窗口、错误凭据、HELD和STOP。原继续已在失败前执行通过；剩余实例／配置准备／原生静止仍执行中，不先补成整组通过。

本轮追加test_task_start_instance.py仅修正过时夹具和负例，未修改任务模型准入生产代码。新C39门槛测试及独立进程测试源已整理，相关本批lint通过；481生产文件格式仍通过（连同单个修正测试检查时工具显示482文件）。


## 11:51 已结束检查与实际保存范围

- 剩余实例／配置准备／原生静止直接调用方15项184.90秒通过；加上前轮失败前已通过的原继续，当前没有在运行或待取结果的检查。既有失败按上节保留，不合并重复轮次制造完成计数。
- 非法JSON／Unicode确定前置拒绝后111项15.20秒通过；末次类型保持修复后三个协议／私有记录文件117项14.39秒通过。true与1、1.0与1不再视作相同原metadata，错误创建回执／原metadata搜索不形成ACK，权限未知只能等精确原类型恢复后只读确认。
- 三生产模块及新原生测试／C39门槛测试lint通过；481个backend/app文件Ruff格式通过，git diff --check退出0，仅其他既有frontend/tests/application-router.test.mjs提示CRLF转换，未为此改该文件。无前端源码变更，本轮不新增前端产品／浏览器结果。
- 11:51原生netstat8000／5173／5174无监听，HEAD仍28a7c9e13c73a9d386081a6dd894244b51746a45，正式设计摘要与开轮相同。没有启动／更新正常服务或业务库。相应Temp目录均断言结束后不存在，剩余静态链接／原子临时文件收口另核。

生产3文件聚合SHA256 ca5f148b747b271392b76b267856370444751d67652b9f6e688c27363f9028b2：

| 实际源码 |
| --- |
| backend/app/code_tasks/task_native_actions.py |
| backend/app/infrastructure/opencode_instance_control.py |
| backend/app/infrastructure/windows_private_record.py |

测试／辅助4文件聚合SHA256 af88f02f363cbd3046201b6e46a7320d41ab57175327aa7b200de5f291034cb1：

| 实际源码 |
| --- |
| backend/tests/infrastructure/test_v20_native_permission_application.py |
| backend/tests/infrastructure/test_v20_opencode_instance_control.py |
| backend/tests/code_tasks/test_task_live_configuration.py |
| backend/tests/code_tasks/test_task_start_instance.py |

聚合算法为相对路径字典序，依次UTF-8路径、NUL、文件原字节、NUL累计SHA256；不跨集合用文件数计算进度。代码没有半成品函数；完整C39权限配置、原生在写受控停止、正式驱动／系统／供应方及合格报告到交付联合仍分开未完成，不因基础方法专项通过改标完成。

## 11:59 最终收口

自香港11:01推进至11:59，本轮三生产及四测试源码均再次匹配上节摘要，没有待取结果或半成品函数。7份关联文档链接缺失0、当前映射5条业务行同表6列，所有本轮源码／文档原子临时文件0；自有walle-v20-permission临时目录剩余0、工具dry-run JSON／截图0。11:56正常服务三端口监听0，HEAD和正式设计摘要保持。未提交／推送，未改正常业务库或用户服务；完整C39权限采用及其余正式环境／供应方／交付缺口按当前断点继续，不能把本轮基础层当完成验收。
