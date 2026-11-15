# 受信本地部署与正常启动（2026-11-13）

本轮香港14:25:51起按用户两小时要求接续，基线master／28a7c9e，Git折叠432条，保留其他改动。BE／FE正式候选DRAFT摘要保持，独立[实施前迭代](../../iterations/pending/v2.0/WALL-E.受信本地部署组装与正常启动迭代V1_V_2.0.md)不合并。源码／格式结果原子保存，无用户库、服务、Git目标、SYSTEM／WFP或供应方操作。

## 单元A：原正常启动读取受信来源

local_deployment.py严格成对来源、摘要、本机绝对路径、非提升非AppContainer身份、原registration类型及路径／Guard程序固定；源持有覆盖实际uvicorn生命周期，无配置不探测，异常不回显源正文。__main__.py原正常入口传入原create_app，应用异常仍属应用，不在yield外捕获成部署错误。task非null此阶段拒绝，未借此开放Coding执行。

使用项目.venv／Ruff，TemporaryDirectory、tools.quality_gate.environment；固定入口tools/python-v20.py tools/quality_python.py，pytest -q -p no:cacheprovider --tb=short --basetemp <临时根>/pytest。真实当前用户NTFS；测试的配置及PE假程序均是临时输入，不安装或运行Guard。

- test_local_deployment.py 36项通过。含严格结构、未知字段、布尔／浮点、绝对路径、SID／重复根／范围、无配置零IO、摘要错前置拒绝、真实配置／程序生命周期固定、应用原异常保持。
- 加test_v20_startup.py首次36通过／2失败：原r44正确拒绝__main__来源摘要变化。依既有schema-v20-release.py发布新db20-r45（manifest f5064ecbd94e28881523ee8bc751cd7364f4425d6768c3f93e83998ae20dac00），没有修改来源校验器；旧r44保留。fresh.v1.sql、upgrade-151.v1.sql、objects.v1.json三文件与r44原字节一致，未执行用户数据库维护。
- 新资源下同两文件最终38项23.81秒通过。
- test_v20_local_deployment_startup.py新增两项9.04秒通过：新解释器执行真实backend.app main、真实应用及Schema200生命周期；仅uvicorn监听器和Guard注册worker为具名夹具。实际源固定直到服务返回，原Worker.start／close调用、零LLM／零任务；错误摘要在应用／数据库初始化前拒绝。不当作正式Guard／原生／OS部署证据。
- 香港14:31 socket只读核对8000／5173均无监听；无服务启停，旧库及初始化资产不动。

本轮后续仍进行task引用绑定及Guard本地组装，最终检查／源码摘要继续追加；不能把A当作完整部署完成。


## 单元B：实际TASK资源组

task_deployment_configuration.py把严格task组直接构造既有OpenCodeBinarySource／OpenCodeRuntimeBundle／TaskExecutionPlan／TaskLaunchInstallation，引用从单一execution／bundle来源导出，agent具名且安装对象deny-all；不接受任意permission／arguments／ready。缺workspace、旧版本、非loopback／重复端点、布尔时间／内存、未绑定bundle等在IO前拒绝。正常main同一部署入口在创建应用前以原ZIP固定摘要、SDK blob及完整离线清单预核，并持有二进制／运行包manifest，原配置组摘要仍由实际driver启动时读回。没有OS或模型准入提升。

test_task_deployment_configuration.py＋test_local_deployment.py最终62项4.20秒通过（26 TASK＋36基础）。实际NTFS／ZIP／SDK／资源闭包路径使用隔离PE和最小API夹具；发布方ZIP摘要／SDK blob只在测试里绑定假输入，不是正式OpenCode证据。原镜像或包manifest运行期间不可重命名；篡改镜像／ZIP／SDK／额外文件均在应用前拒绝。


## 单元C首批：原连接内核发现

windows_pipe_peer.py新增discover_registered_pipe_client，经内核连接PID立即固定ObservedProcess及原NamedPipePeerLease。Host的accept_registered复用原连接／首端点／Server，发现仅提供候选，原创建时间／用户／非提升非AppContainer／原镜像对象／ProtectedBackendProgram及owner_epoch检查不减。连接失败未读首帧时保留UNADMITTED，关闭本次原IO后才能从同一首端点退役；不将该路径用于已有协议帧的旧会话。异常嵌套原所有者保留在Host，不丢本机句柄归属。

原Host已知进程／新发现两模式的真实双会话、超时取消／同首端点、原Git请求／回执，加管道peer／endpoint关联共35项29.83秒通过。新增真实活客户端错误镜像、连接后取消、嵌套未知所有者3项1.91秒通过；均未读取首帧、Server无controller记录，活客户端仍活、原端点退役不替换；仅受控测试Job最终清理本轮进程。ProtectedBackendProgram仍具名测试端口，不是正式服务或包／SYSTEM证明。

## 单元C后续：失效连接、原资源停止和Guard部署组

poisoned帧读取后仅退役原连接I/O，不能将未知请求重发或丢Server所有者；BAD_JSON／BAD_SIZE／静默超时等新增6项和部署62项联合68项6.00秒通过。原Server／controller新增安全stop_owned后仍使用原close拒绝活动资源的保护；Host及原命令10项121.85秒通过。

GuardDeploymentOwner严格读取受信DEPLOY20-GUARD-1、本机普通backend SID、实际SYSTEM先验门槛、后台程序manifest及完整TASK组，按原身份open根与持有源，再创建实际首管道／journal。当前普通用户下的正向组装明确使用具名SYSTEM门槛及任务准入夹具，不构成正式系统证明。首轮25项23通过／2失败：夹具program_ref长度不合规、Guard导入纯工具间接加载database。修正夹具及提取实际公共算法后，部署／Guard／幂等97项＋8subtests7.50秒通过；完整TASK新增4项初次3通过／1失败为测试误读bundle.reference，修正测试字段。新协议后原Guard完整TASK／SCM／部署115项4.93秒通过。

canonical_input原算法提取shared/json_canonical.py，exact原算法提取shared/strict_objects.py，Guard基础设施不依赖业务DB／model_profile；原业务调用同一函数，不复制字节规则。幂等非Success回调TypeError，事务回滚／业务结果不变。当前backend/app全量Ruff format检查497文件通过。部分旧infra整文件lint仍有原有告警（如audit_repository未用拆包值／日期表达式），不为import变化重构这些旧业务分支；新增模块逐项lint处理。

## 单元D：正常SCM入口

windows_guard_service_host.py与backend/runtime_guard/__main__.py实现实际ctypes SCM dispatcher／ServiceMain／handler ABI。固定installation_ref派生服务名，配置SHA／根身份未核实不RUNNING；取消事件跨控制线程，原Guard所有者只由ServiceMain线程构造／serve／close。失败只报固定代码和非零退出，未知owner不重复关闭；入口失败结束自身Guard进程的分支通过注入检查，不实际结束本工具或用户服务。24项2.06秒通过，SCM使用具名端口，未实际安装／注册／启动SYSTEM服务。

原多TASK停止首故障提前返回已修正：closing逐项请求原callback、settled不重复；到期也不跳过后续已知Job的原stop。实际registry／SCM及回执丢失目标首次40通过／2失败仅因r46来源漂移，未到达管道；新资源下原挂起进程＋正常main／startup共6项46.61秒通过。真实CREATE回执丢失保持原UNKNOWN／未resume，服务停止封原nonce及controller、核对原根EXITED／原Job完整为空后释放一次，不重发CREATE，不伪造业务清理。

## Schema来源最终资源（当前）

本轮idempotency及相关import格式更新后按原发布器生成db20-r47，manifest aff74aaff36faed08b8725cf9d3ffb6f00fde3df524ccc99af4ef950c051ce05；r44／45／46全部保留。fresh.v1.sql SHA256 9da3375bcaed99e9b492f4fda04119eef78dcc5784c2b5daf13ac118f28957ad；upgrade-151.v1.sql 9abcb2a3a7f662b4ca61733cb3bd34d4b894f848db2240fe7b4940e75ddb671c；objects.v1.json 62eeeaee0ce469548abc4b4916a39c41dd28e2040b2c88c8ff035203988540c5。四个发布目录三资源原字节一致，不打开正常库。

## 单元E进行中：独立检查正常部署

schema2／DEPLOY20-BACKEND-2及DEPLOY20-GUARD-2严格新增checks与独立Guard runtime根；schema1仍只接原字段。common check_deployment_sources.py复用原项目检查／浏览器driver／runner／CasePack类型；backend check_deployment_configuration.py投影原Coding／Testing准入，不将Guard SYSTEM私有根当后端可读资产。Testing不依赖Coding／OpenCode，仍不提升delivery_runtime_admitted。首批严格来源／引用／角色／版本43项1.75秒通过；实际Guard检查资源组合及正常main携带CasePack尚在实施，不能标整体单元完成。

## 单元E完成：独立检查实际源组合

严格来源43项1.75秒通过后，实际NTFS／CasePack／正常main／Guard组合11项12.58秒通过。普通main实际携带原TestingCliAdmission／TestingBrowserAdmission／CasePack进入原应用生命周期；Guard在没有TASK／OpenCode／模型的情况下打开实际原runtime根和首管道，读取原runner完整闭包／PE／依赖引用及原准入记录。角色门槛在测试中明确为具名SYSTEM夹具，准入checks摘要也是专用假证据，不当正式WFP／LPAC或供应方证明；篡改源、runner多文件、错误runtime_ref／driver闭包／证据摘要／PE均拒绝。后端仅读取其数据CasePack，不尝试访问SYSTEM资源。

## 单元F：正常Coding模型组

model_deployment_configuration.py复用原Profile、CodingModelAdmission／Deployment，固定完整元数据和显式假环境。模型初次37项34通过／3失败：测试用了journal带LF摘要而非Profile canonical无LF摘要；修正后36通过／1失败为测试误读agent_ref属性，再改为原agent。最终模型37与退出peer7共44项9.73秒通过；新进程原main／真实app／Schema200生命周期携带模型组已执行，官方ZIP及SDK固定来源仅测试端口，零LLM／零code_tasks，原凭据只为fixture-only值。原模型网关及授权后续完整回归见词法记录，不以配置成功宣布供应方／价格已准入。

## 单元D故障复核：常驻、停止竞争及未知清理

原后端EXITED时Host现在明确进入FAILED／原poisoned帧退役，保留首端点／Server；未知进程观察不假报退出。Owner构造收到retained_owner不立即重试子close，失败close锁存、成功close幂等。SCM实际跨线程组合曾发现连接派发前取消产生GUARD_HOST_ACCEPT_CANCELLED而没有ABORTED状态，导致正常STOP被误报非零；现明确记录原ABORTED并走原退役。实际配置／journal／首管道在ServiceMain另一个真实线程构造／关闭，主控制线程只取消；SCM API为具名端口，原真实原生资源未替换。SCM29＋peer7最终36项3.53秒通过。未知构造／原close／dispatcher失败均保留原owner、不盲目重试，入口自身失败退出仅注入检查。

## 工具、共享联合与当前来源

tools/inspect-code-deployment.py读取明确源，backend不创建应用／库／连接或模型调用，guard只结构检查不创建journal／首管道。CLI5项6.24秒通过；成功输出改到资源正常关闭后，连同幂等非Success实际回滚／claim释放的16项＋8subtests9.59秒通过（CLI最后输出位置调整待当前共享联合覆盖）。

最终15文件部署联合288项＋8subtests103.66秒通过：local/task/model deployment、Guard配置／SCM／discovered clients、check sources／composition、CLI、真实main、原startup、原idempotency、runtime_control_git、原peer／endpoint。命令仍为tools/python-v20.py tools/quality_python.py <这些专项文件> -q -p no:cacheprovider --tb=short --basetemp <专属临时目录>/pytest，environment()禁止用户数据／密钥及外网。没有全项目或浏览器产品验收。

词法相关50项＋12subtests123.93秒通过，源码及性能边界另记；最终当前资源为db20-r48 manifest bf188e05df22f548ebb2e6dfab10132ba198ecea7240d4a312d14ca1579e5a39，r44／48三份SQL／objects逐字节相同，原r45—47保留。format500文件、受影响新模块及纯共享/Guard/runtime lint通过。香港16:07清理工具dry-run JSON=0、screenshots=0，git diff --check通过，未清理其他正常输入或数据。

原生20参数与共享JSON／内容／报告接口联合仍在执行，最终结果稍后追加。已观察到1项trusted driver frames skip：复制CPython在LPAC下0xC0000022、尚无帧；原LPAC清理验证通过，不能当浏览器帧或正式功能通过。本轮没有改该skip或放宽隔离。

## 公共算法的受影响业务回归

共享JSON／内容hash／原控制记录／历史模型快照／报告接口及最终CLI联合103项＋10subtests77.17秒通过。文件为code_tasks/test_content_manifest.py、test_content_manifest_git_vectors.py，infrastructure/test_v20_runtime_launch_journal.py、test_v20_guard_controller_records.py、test_model_profile_audit_data.py、test_v20_command_http.py、test_v20_deployment_inspection_cli.py和test_testing_report_api.py；使用同一隔离命令形态，无原始日志持久化。CLI成功输出在原源正常关闭后才产生。

## 原生组合的未完成证据（16:18）

原生20参数组在600秒总限时结束，没有完整pytest通过汇总，不能记整体通过。已出现trusted-frames skip：复制CPython在LPAC下0xC0000022，在首帧前退出；原Job／目录／网络夹具的清理证明通过，仅说明清理，不说明driver帧或浏览器功能。

单独TESTING_VALIDATION_GROUP加faulthandler_timeout=30的隔离诊断出现Windows fatal exception: access violation，进程异常退出。可见主线程在固定Git包校验／原Guard CREATE，另有原控制方观察线程；堆栈采样不足以认定某个FFI或新代码是根因，也未证明诊断定时器无影响。未放宽LPAC／ACL／WFP或将错误改为通过。已启动不带额外定时dump的一次同场景复核，并把原生联合缩到实际受影响的8参数（项目检查、Testing项目检查、多任务、控制方退出、两种Host连接和两种回执丢失停止）。最终结果待追加。

## 原生受影响路径最终结果与未通过项（16:22）

缩小后的8参数完整通过，196.40秒：PROJECT_CHECK、TESTING_PROJECT_CHECK、PROJECT_CHECK_MULTI、PROJECT_CHECK_CONTROLLER_LOST，以及Host已知进程／内核发现两模式、CREATE回执丢失的原连接清理／服务停止两模式。使用原真实Windows管道、进程／Job及私有记录，受保护程序与网络／部署证据仍具名夹具；不当正式SYSTEM／WFP／供应方证明。全部原资源按既有所有权清理，无未知原生close被自动重试。

TESTING_VALIDATION_GROUP不带faulthandler_timeout的单次复核300秒仍超时，没有完整结果或通过证明。不能据此断言诊断器导致先前access violation，也不能判产品已通过／已失败。该复杂组合与LPAC中CPython首帧问题保留为具体未完成项，不再扩大重跑或修改skip。下一步按现有measured_dispatch／timings记录受控阶段耗时及原backend进程状态，区分固定Git包重复核验／实际阶段等待／原生异常，不跳过源验证或降级身份。

16:21只读CIM仅按本轮专属临时目录标记过滤，已超时／已完成的检查Python进程匹配0；没有停止用户进程。8000／5173socket均无监听，本轮未启停用户服务。502文件（backend/app＋backend/runtime_guard）Ruff format通过；最终git diff --check通过，仅原其他前端文件有Git CRLF提示；清理工具dry-run JSON=0／screenshots=0。临时目录finally清理，没有原始JSON／截图／录像／日志留存。

本轮香港14:25:51至16:25，约两小时持续推进后在完整代码单元结束；没有在途检查，未完成原生边界已保存。结束时后端Python源码＋独立Guard＋只读工具共503文件的路径／原字节组合SHA256为a7d6ff8f48da00d0c541bf5779f557792f96a9b2835e761812a15ccc0fc0a44d（路径UTF-8、NUL、原字节、NUL，按相对路径排序）；设计两份摘要本轮再次核对未变。该指纹不替代Git提交或产品验收。
