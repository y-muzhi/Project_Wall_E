# Guard专用程序包与公共构建链（2026-11-14）

## 环境、代码及范围

本轮香港16:19:11开始，HEAD28a7c9e／既有503条工作区改动，保留其他任务。BE0.17-draft-17／FE0.16-draft-16、Schema200／SQLite3.54.1／db20-r49不变。仅源码、固定本地包及临时自有文件／进程检查；未安装SYSTEM／WFP、未操作正常数据库／Git目标或更新用户服务，零模型／计数，未提交推送。源码原子保存，资源／旧包保留原字节。

## 当前已执行

- 共享清单抽取：旧后台容量测试首次patch旧模块常量，1失败35通过；指向实际共享decoder后36通过（2.23秒），原断言／限额不变。
- 三文件联合：test_v20_guard_package_preparation.py、test_v20_guard_backend_program.py、test_v20_backend_package_preparation.py，51 passed（2.93秒）。实际NTFS覆盖原文件写删锁、完整成员／新增空目录、文件变化／缺失、错误摘要、硬链接、ADS、取消、未知关闭保留与不重试；新GuARD政策与原后台政策独立、不能冒充ready。
- 命令通过tools/python-v20.py tools/quality_python.py <上述三文件> -q -s -p no:cacheprovider --tb=short --basetemp <本轮TemporaryDirectory>，quality_gate.environment／finally stop_owned及临时清理；普通完整Windows测试身份，工具自身AppContainer不充作产品身份。
- 新生产公共模块／Guard入口及三打包工具Ruff lint通过。完整backend/app格式收尾待执行，不提前记通过。
- 初版1631固定Guard包生成，manifest8160c54f1f09e98eadad2a49cdfce7d1a1fbfebc2770952d4f4f7125e76dd832／源06bbda53b5a188664b1501912cd30f92aa7a5bf8f7cf83434c923d0498464892，338成员31216907字节。
- v20_frozen_guard_program_worker.py --package <1631绝对路径> --sha256 <上述摘要>实际六项通过：运行依赖导入、完整包、错误摘要、缺摘要、混合探针参数拒绝、普通控制台无法进SCM，包前后原字节复核。此处没有安装服务或SYSTEM角色。
- 后续检查生产guard_control_git_prepare.py／windows_native_process.py发现固定BUNDLE_PARENT Git路径仍是Guard实际依赖，1631缺此闭包，不可当完整Guard运行准备。已补固定Git全来源与CONTENT20-SECRETS-1资源、探针真实读取校验，不带前端／SQLite／SQL／设计正文；1631成功证据仅限上述导入和入口，保留失败边界。
- 源码--verify-runtime已实际verify_bundle_bytes、load_secret_policy通过，并确认Guard依赖未导入业务DB／service／code_tasks／sqlite3。

新1640 Guard／后台共享链实际构建在途；结果未取前不记通过。SYSTEM赋值／WFP／双LPAC SERVICE／供应方及完整Coding报告交付仍未验证。本轮scope与技术规则见pending迭代，不自动合并正式设计。香港16:31只读现有8000／5173无监听匹配，未变更服务。

## 完整资源与实际运行更新（香港16:57）

- 1640完整依赖构建首次拒绝，未发布目标目录；原临时路径下最长Git成员243 UTF-16单元，超过既有240规则。缩短本轮构建私有临时前缀，限额不变；公共构建增加最终目标全成员路径预核，不能只保证临时目录可用而发布过长目标。相应新增拒绝测试，不创建无效目标。
- 1643 Guard完整Git／政策资源探针、完整包及自检通过：manifest18e8d9021d9474518c80dd153c392c82f753f5d3b72ceb3416476096c172b449／源01360dcd7cca11782c8223da5a13c48376fafe8e1f2d620e67a16b9d75d8e825，528成员188257472字节。但冻结分析引入未使用的通用SQLite组件，因此继续收紧包，不把此包当最终最小Guard资源。
- 最终1646 Guard：manifest5d6940bf01381e8e508a04874ef0b31da7f44c6e3d0bbb943af4aa3395bfacf3／源8af28c04bab820265de0dad28532a896bb6a7cf5c9dec60bafd68369ca25af7b，526成员186505424字节。保持完整固定Git及CONTENT20-SECRETS-1，只排除Guard不支持的sqlite3／_sqlite3／业务DB／code_tasks／service，原后台不使用这些排除。实际全部成员确认无_internal/sqlite3.dll或_internal/_sqlite3.pyd。真实六项EXE worker再次通过，包含实际Git完整归档／成员和固定政策读取；普通控制台启动仍拒绝。
- 1643后台共享构建回归：manifest321b39cc82e5859f8bd894fb3423d2105f40aded7e2805b2280b6d4797e910ab／源0e5fa5a483732f646423dd9dec548035cf6d4b85649ae38dc86a836b7c9e0cf7，1798成员265780468字节。当前前端实际类型检查和编译、固定SQLite3.54.1／资源探针通过；这是该时刻不可变快照，不把后续Guard专属构建参数说成已进入旧来源。
- 新1650浏览器包：manifest81586dfdc13a4d7c3ab6bb3ecb94bc06e93df65fda5d3c6b466e97e2b5d290ba／源8076c9339f33095cc3669a11210807f627017e2286908b2491155fff84faffff。相同已锁定官方来源，包含当前新增公共程序模块。与1643后台实际原LPAC／Job浏览器页面及后端GET联合通过：内层1 passed109.59秒／外层1 passed111.77秒，同一场景只计一次；全1798成员前后长度SHA核验通过。五HTTP／资源检查、零任务／模型、自有服务停止和临时数据清理，仍是普通自有SERVICE夹具，不是正式双LPAC SERVICE。
- 共享程序／原后台／新Guard／SCM／部署／只读CLI六文件联合116 passed（9.85秒）；新增最终目标路径测试晚于此轮，最终联合待收尾。生产backend/app509文件format与本批Ruff lint通过。

## 不同主进程权限下的新登录来源

普通来源与宿主权限不同是正式Guard前的重要缺口；相同用户／相同权限的对照不能证明实际克隆了哪一方。初次用外部复制令牌CreateRestrictedToken后CreateProcessAsUserW创建诊断宿主返回1314，属于测试准备权限边界，未执行LogonUser，不据此判断产品派生失败或改生产来源。

改用本轮自有原Job内已创建的普通子进程，仅在该子进程自身Token中移除全部特权（不启用权限、不改账号或其他进程），保留外部原后端5项特权不变。生产CheckLogonSession实际在此0特权宿主中运行，派生结果取外部原后端5项特权、同原用户／Session、不同AuthenticationId，模拟线程恢复为无Token；3 passed（1.82秒）。这证实该环境中的有效来源不是宿主主Token，仍不冒充SYSTEM实际赋值／服务安装证明。新增自有主Token恢复后不变化的断言另随最终联合复核。

复核入口：test_v20_check_logon_session.py及v20_check_logon_source_affinity.py；不包含候选代码、不使用真实凭据或网络认证。原准备失败全部在自动清理测试目录，未留原始JSON或日志。一手约束见[CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken)、[CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)、[LogonUserW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-logonuserw)。

## 第二小时接续：真实Git、SERVICE与源副本边界

原隔离HTTP／两种Git格式联合3 passed（145.84秒），但SERVICE实际值为endpoint_unavailable，不能将pytest允许的UNAVAILABLE分支改记真实联通。两Git格式的原受控prepare／commit／只读后核对、HEAD／索引保持及完整原句柄清理为本轮新结果；没有操作用户Git目标。

进一步六项非网络能力对照8.65秒，仅创建未连接IPv4／IPv6 socket并尝试_overlapped导入，无connect／bind／listen／发包。registryRead分别与lpacCom、lpacAppExperience、lpacSessionManagement、lpacCryptoServices、lpacIdentityServices组合及单项基准，三个初始化结果均10013。没有修改生产白名单、安装WFP或授网络能力；这不证明正式WFP／loopback环境必然失败，只说明这些非网络系统能力不能替代缺失的正式网络准入。独立SERVICE迭代保留pending。

Guard启动资源已实际准备：guard-bootstrap-prepared-20261114-1710，install-plan.v1.json SHA971166b94d70c0685bcca3d53bb4e8e1f24b3ef1380b50ccc8e2acf74feba9ac；guard-deployment.json SHA7515452f7bb5ab727ae42a60fe1ac955091c924c775d90af275885dcd9093989。只绑定两个本轮真实包、真实普通后台SID及显式全新目标，原decoder验证，无伪造FileID或OS证据；C:\ProgramData\WALLE.RuntimeGuard.V2.Test.20261114-1710未创建。task／runtime／checks均null，是最小SCM启动输入，不能当完整执行部署。八项准备边界及来源／目标／权限联合见27项（3.94秒），临时副本最终路径补强及启动资源／来源联合35 passed（4.76秒）。

源码编译副本补强采用原源租约、每块写长度、flush／fsync及独立目标原生读回；1MB以上短写和等长损坏两实际故障注入均拒绝，原文件字节保留、原源／目标句柄关闭可重命名，未发布编译产物。先前只比源CAS不足以证明编译副本，此处未关闭检查或减少内容。补强后的实际新包构建仍需收尾，不能将旧包构建算新链证据。

下一原生联合扩展APP-CODE-PUBLISH：实际三角色／明确修复后已发布的原Guard候选，除不存在报告404外，明确创建一个诊断Testing任务和FAILED报告负例，必须409 TEST_REPORT_NOT_ELIGIBLE且不改CodeTask／不生成Acceptance或Delivery；报告执行是明确负例夹具，不伪称原生PASS，不patch生产_selection／qualify_report。原设计PRODUCT／ACCEPTANCE／四阶段／前后端集成证据要求保持。结果取完前不记通过。


## 最终源码快照与入口复核（香港18:00接续）

公共编译副本补强后实际重建两个新目录，既有1631／1643／1646及1710准备资源均保留，不覆写旧字节：

| 准备目录（backend/distributions/windows/） | manifest SHA256 | 来源 SHA256 | 完整成员与总字节 |
| --- | --- | --- | --- |
| guard-prepared-20261114-1730-snapshot | c10a858e6f0ef1e1204f016ab1aadc75e7d6849e098162d5cb7219f26663046b | 99fb920184fbbe9139dbf54e9104e81445beaa0d492d87dbf02ed5e2479af478 | 526／186505424 |
| prepared-20261114-1730-snapshot | de33c0afeb4017d23d84f80c2d9263356dbe4d7a724b85f972e96f84b92a6192 | 25ef4373c5c8484d7294acd524ef92361c31e5b5d26d805987d3e735d9fac08d | 1798／265781262 |
| check-browser-20261114-1650-program-manifest | 81586dfdc13a4d7c3ab6bb3ecb94bc06e93df65fda5d3c6b466e97e2b5d290ba | 8076c9339f33095cc3669a11210807f627017e2286908b2491155fff84faffff | 完整源包核验通过，原矩阵／取消2场景235.78秒 |

上表来源摘要已在本次后续实际读取复核一致；不由同成员大小推断新EXE字节等价。两个1730新EXE／base_library.zip均与旧包不同，已经分别实际检查：

- 固定build锁只安装临时工具目录，经实际源副本读回、前后原源CAS、完整manifest及入口资源检查发布。后台实际运行前端类型检查／生产编译，固定SQLite3.54.1不变。命令为tools/build-windows-guard.py及tools/build-windows-backend.py的原main入口，显式全新输出和固定program_ref；后台带--build-frontend。未更新用户服务或frontend/dist。
- 最终Guard1730再执行v20_frozen_guard_program_worker.py --package <1730绝对目录> --sha256 c10a…346b：六项实际EXE探针通过，固定Git／内容政策、全成员原字节前后核对，错误／缺摘要／混合参数拒绝、普通控制台正常服务入口拒绝；未安装SCM。
- 最终后台1730＋浏览器1650执行v20_isolated_application_browser.py --backend <1730绝对目录> --manifest-sha256 de33…6192 --browser <1650绝对目录>：同一原LPAC／Job应用场景外层1 passed138.04秒，内层1 passed135.74秒，只计一次。实际大JS、三页面及GET均成功，五HTTP／资源检查通过，全1798成员265781262字节前后核对，零模型／零Coding任务，本轮临时新库和自有后台停止清理。此SERVICE是明确普通测试夹具，不是正式双LPAC SERVICE或WFP证明。
- 九文件联合130 passed（13.22秒）：test_v20_program_snapshot_copy、guard_bootstrap_preparation、guard_package_preparation、guard_backend_program、backend_package_preparation、guard_service_host、guard_deployment_configuration、deployment_inspection_cli、check_logon_session。tools/python-v20.py tools/quality_python.py各完整文件参数，-q -s -p no:cacheprovider --tb=short --basetemp <自清理临时目录>；包含混合权限宿主恢复后主Token仍0特权的新断言。与旧116／51等存在重叠，不累计成不同需求总数。

## 原候选上的失败报告拒绝

在原test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_HANDOFF]扩展v20_coding_failed_report_worker，联合1 passed（621.65秒）。原Guard真实三角色交接、候选发布、明确修复和项目检查沿原链路；模型／执行对话仍为明示离线夹具，无付费调用。

新增单元在实际已发布候选上，先确认没有自动创建Testing任务，再通过实际API明确创建诊断Testing任务、原产品编译／seal测试包。FAILED报告的执行事实用_save_fixture显式负例构造，未冒充原生PASSED或正式验收；未patch生产_selection或qualify_report。实际报告GET证明FAILED、delivery_eligible=false且candidate_id对应原候选；实际关联POST返回409 TEST_REPORT_NOT_ELIGIBLE，同键重放仍409且业务错误相同（request_id元数据允许不同）。任务state_version、AWAITING_TESTING／TESTING、报告／Plan引用保持，Acceptance和Delivery记录均0。

此项补足“存在但失败报告”的实际原候选拒绝，旧不存在报告404仍保留；不代表完整PRODUCT／ACCEPTANCE、四阶段、集成证据合格报告接收或最终C64交付完成。

## 启动资源实际写入与只读核验

最终准备器对部署文件、计划和README每次写长度、flush／fsync、关闭及原生独立读回逐项检查，唯一数据流、实际长度／SHA一致才发布整个新目录。短写／等长损坏／刷新错误分别注入三个文件共9负例；实际17 passed（3.83秒），含原8项边界。无部分输出、ProgramData安装目录或源包变动，暂存清理，原文件句柄可释放重命名。最初直接lint该测试发现导入pytest fixture被识别为未使用／遮蔽，改用原fixture模块显式引用，未删原生fixture；工具及该测试lint／format通过。

实际新资源guard-bootstrap-prepared-20261114-1800：
- installation_ref=0cedd4c6f77fb9cb243e5b2064d95b220a10c9076bed70f52fb1b9b5d055c539。
- install-plan.v1.json SHA cc095d7f17b3200b8f04d8b3545dff70515f4d2031ac626da5e0cd25e62cb7a9。
- guard-deployment.json SHA e0e2b2d84da2cff3eedc6eb2d00cf3f8750847ce4beee551b212d88b645b2ddc。
- 明确目标C:\ProgramData\WALLE.RuntimeGuard.V2.Test.20261114-1800未创建，绑定上表两个1730固定源包，task／runtime／checks仍null。
- tools/python-v20.py tools/inspect-code-deployment.py --kind guard --manifest <1800配置绝对路径> --sha256 e0e2…b2ddc实际返回GUARD_SOURCE_SHAPE_CHECKED，未打开SYSTEM证据／journal／管道。首次误用1755旧目标摘要ce30…6b6a被严格拒绝，无输出正文；修正为当前原字节摘要后通过，不弱化decoder。1755中间资源保留，当前使用1800输入。

## 原SCM接入尚缺的进程查询证据

只读现有Schedule状态RUNNING后，普通非提升／非AppContainer测试身份尝试原ObservedProcess返回PROCESS_HANDLE_UNAVAILABLE5；进一步分别QUERY_LIMITED_INFORMATION(0x1000)、SYNCHRONIZE(0x100000)、组合(0x101000)均拒绝5。未控制／停止服务或修改DACL／Token。

随后固定Schedule／EventLog／Winmgmt／Appinfo／Themes五项SCM_QUERY_STATUS均RUNNING、type48（共享进程）；三种进程读权限均拒绝5。当前自身主Token为中完整性S-1-16-8192，RestrictedSids数量0，非提升／非AppContainer。只读TokenHasRestrictions初次使用DWORD严格helper因实际返回长度不符安全退出，后续不解析该额外字段；生产helper不改，也不由该未解析字段判断身份。所有本轮查询句柄关闭，无调试权限启用、无进程写入。

这些是既有共享服务而非本项目OWN_PROCESS Guard，不能断言本项目服务必然不可读；也不能由SCM服务配置／PID替代原SYSTEM主Token和实际镜像身份。正式安装后的普通后台对其原Guard进程及主Token的最小只读可见性必须实际核验，否则现有connect_registered_guard仍会安全拒绝。当前未实施自授进程权限、修改共享SYSTEM Token或跳过身份核验。只读API语义参考[GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation)及[TOKEN_INFORMATION_CLASS](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)；本段返回值来自本机实际观察，不由资料推定。

正式SYSTEM实际派生赋值、受保护ACL／原进程可读性、WFP与两SERVICE／OwnedBrowserRelay、合格Testing报告及完整交付仍未通过；ready=false。


## 最终发布链与关闭边界（香港18:11接续）

write_new_verified_file已成为两程序manifest和启动资源的共同新文件写入／fsync／原生读回实现；原后台发布前也通过ProgramPackageLease核对实际清单及全成员，才可新目录原子发布。此前1730没有这次最后工具修改，保持旧快照原字节。本次139项联合15.04秒（9文件）通过，不能与先前130／116机械累加。

1810最终Guard：backend/distributions/windows/guard-prepared-20261114-1810；manifest78b68711be8d1a3fcf5edbba4db85869cb2720706256c84467d81490c1bfd57b，源1a072697b9d0c994be49a18ec29d130e6e0044138e3f28f650e4a53ba0e060fc，526成员186505424字节。实际六EXE探针、完整原字节前后验证通过；无SCM／SYSTEM安装。

1810后台：backend/distributions/windows/prepared-20261114-1810；manifestcba5355e9b8cfa11c33a666bffadee5430b84cdd64105d440e302fc97bf910fd，源fba1cfc367f69e41b0a556c74d6fcc3632f722001fce4e0c8091ca6ac8136ddf，1798成员265782223字节。实际前端类型／编译、固定SQLite资源探针、发布前全包读回通过；与1650浏览器再做真实隔离应用检查，外层1 passed140.66秒、内层1 passed138.39秒（同场景不重复计），大JS／三页／五HTTP检查与全包前后字节核对通过，自有后台已停止，零模型／任务。当前浏览器源摘要仍8076c9339f33095cc3669a11210807f627017e2286908b2491155fff84faffff；两程序来源及浏览器APP来源均已实际原生重新计算匹配。

绑定这两个1810包的启动资源guard-bootstrap-prepared-20261114-1815：
- installation_ref70396624ef329e8209559d10a410ec9cc20b068bf91984af635354987b49cf27。
- 计划SHA93e8286cc558eaa43958beb62da78d590ddb618c3ffb97f4318d9ece1ffd2d85；部署SHAd1549044a932512760fca42d7eb1e505509b27de0def9385869d6b4adb62d19a。
- C:\ProgramData\WALLE.RuntimeGuard.V2.Test.20261114-1815未创建。实际原canonical计划、两个原manifest摘要、服务名／参数数组／image_path以及最小task／runtime／checks=null均核对；原只读inspect返回GUARD_SOURCE_SHAPE_CHECKED。该资源不自动换绑后续后台。

最后审查发现后台main原有catch会把retained_owner异常打印后返回1。新全包租约会实际产生此类异常，因此与Guard／启动准备器一致原样传播，保留原owner，不重试关闭、不输出成功。实际NTFS租约在原生entry关闭后注入“结果未知”，整个CLI调用原样抛回同一异常／owner，再次close只报告PREVIOUSLY_UNVERIFIED、原close仅1次且不发布目标；含原Guard专项17 passed2.26秒。这个新增用例晚于139联合，与其16旧用例重叠；未重跑无关全项目。

该修复只改变tools/windows_backend_package.py，不改APP／Guard／浏览器运行程序源码；后台来源仍必须更新，1818新后台实际构建在途，不据1810EXE内容相近跳过新包实际复核。

既有明确修复、来源、报告API及交付授权／事务五文件离线26 passed125.63秒；测试报告适用性与交付准入是明确fixture，不替代正式完整产品证据。最终共同工具lint通过，六文件format检查通过，生产APP格式证据仍509文件；未改前端源码。八份本轮文档477个本地引用目标均存在，11个主要修改源码字节完整／语法检查通过，无源码临时文件。git diff --check通过，仅既有application-router测试换行提示。cleanup dry-run JSON=0／screenshots=0，产品资源保留。


## 本轮最终收尾

最后后台目录为backend/distributions/windows/prepared-20261114-1818：manifest086a5bd47b83014ff65c56fbc97599445cb9b5bbc55a70a77725e4755534452b，来源72df72efbfa5b38dbb2ed8cb1f0881b36d009682d5f8adfc809d897bd7195e72，1798成员265782304字节。构建包含最后CLI原owner传播，前端类型／编译、固定SQLite探针、实际全包清单读回均通过，完成后又按当前完整源／编译前端重算来源相同。

最终1818后台＋1650独立原LPAC浏览器实际应用检查1场景通过（外层130.53秒，内层属于同场景不重复计）。三页／大JS、五项HTTP／资源检查及全部1798成员前后核对通过，临时新库零模型／任务，所属后台停止、原监听和测试资源清理；正式双LPAC SERVICE／SYSTEM／WFP仍未验收。

最终启动输入为guard-bootstrap-prepared-20261114-1820，固定1810Guard＋1818后台。installation_ref=a8294fc520ee32d1a42f3c498b204cc47fa5003d0b8fc9b3bca428ae35935837；计划SHA717fa81479f5fdf9b597f6a6435fad307dfcaf9957220c3524a6d4e80dae42dc；部署SHA79957d722ac30cecc9a3321cd93a5de36e416db3509301f434dbea1a8dbbd54e。三实际文件发布／来源保持及计划双包摘要核对通过，原只读inspect成功；计划目标C:\ProgramData\WALLE.RuntimeGuard.V2.Test.20261114-1820未创建，task／runtime／checks=null，未安装服务／ACL／WFP。

本轮最后源码、启动准备和检查均结束，无未保存生产分支；没有真实供应方调用、用户库／正常Git目标写入、用户服务更新或提交推送。上述旧“在途”为当时记录，现行位置依实现进度。共享139项、最后17项和离线26项各有重叠，不累计成需求完成率；整个版本不记验收完成。

18:18最终文档与现场复核：8份接续文档479个本地链接目标存在，完整SHA字符串均64位；最新需求映射12个能力／边界条目均保持六列。默认Git脏状态517行、HEAD未变，源码目录及tools／tests／docs未发现本轮.tmp残留；rg无匹配的退出1按无临时文件解释，不当检查运行失败。8000／5173未见LISTEN、无walle-backend进程或.we-*构建暂存目录匹配；未操作其他进程。最后cleanup dry-run仍JSON=0／screenshots=0，git diff --check仍通过，仅既有换行提示。所有本轮后台检查会话已取完，接续以当前实现进度为准。
