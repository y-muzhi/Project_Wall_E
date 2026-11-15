# 独立登录会话与隔离浏览器修复（2026-11-14）

## 范围及基线

香港14:45用户要求重点解决实际页面自动测试的隔离启动；接续HEAD28a7c9e、Git494条，保留其他任务改动。正式BE0.17-draft-17／FE0.16-draft-16、Schema200及db20-r49不变。仅源码、固定本地包准备、测试自有进程／目录／端口及离线检查；未安装SYSTEM／WFP、未启停用户服务、未操作正常数据库／Git目标、未调用模型或计数、未提交推送。源码以同目录临时文件、fsync、原字节CAS、os.replace保存。

## 已确认原因与对原结论的修正

13:56对照在原共享登录会话中始终WinError5，但有一项未区分：CreateWindowStationW(NULL,0,...)可能打开已有对象。新增CWF_CREATE_ONLY实际得到183，确认系统按登录会话自动生成的窗口站已经存在；此时传入的新安全描述符不改变既有对象。此前“即使给新对象配置包SID仍拒绝，因此当前LPAC本身不能运行完整浏览器”的结论过早，相关历史判断由本文替代，原失败事实保留。

四个固定非网络能力的独立诊断（lpacAppExperience／lpacSessionManagement／lpacWebPlatform／lpacCom）均不能解决共享窗口站冲突，4项诊断5.12秒；没有扩大生产能力集合。

独立临时登录会话中保持相同本地用户SID／Windows Session、新AuthenticationId及新Logon SID后，原主LPAC的四种窗口站创建全部成功。原负例断言因实际成功而失败，此结果是修正旧假设的证据，不改写为旧断言通过。普通进程直接用新登录令牌CreateProcessAsUserW仍1314，去除特权也相同；SYSTEM赋值权限未在普通测试角色中伪造。

单独解决窗口站后，headless初始化错误由Broker返回12推进到11（创建桌面失败）。原根创建只属于实际用户／包SID的新私有窗口站／随机桌面后，继续定位到系统组件初始化。registryRead+lpacCom使固定SDK真实页面加载、中文输入“你好”、点击、文本比较成功；lpacAppExperience只能回应版本，实际页面仍失败，不采用该能力。

## 实际代码

- windows_check_logon.py：从原ControllerPrimaryToken在可恢复的原模拟线程内创建独立会话，只用随机虚构出站凭据，不使用真实密码或建立网络认证。实际同用户SID／同Windows Session、非提升、不同AuthenticationId；无新增组／特权，仅允许NEW_CREDENTIALS实际移除LOCAL和NTLM认证组（固定SID／属性），不接受其他组变化。令牌原句柄不继承，持续来源／状态核验、失败所有权保留、幂等关闭。
- windows_task_native_launch.py及windows_lpac_token.py：只有CHECK_DRIVER使用该活的原派生来源；普通TASK／项目命令仍核对原控制者。真实主／模拟令牌对受持有来源精确核对，不能自报logon。原创建挂起、Job、代码Pin、控制及专属结果管道不改。当前内部回执保存真实driver_logon_source，源句柄在原根停止／令牌释放后关闭。
- check_driver_private_desktop.py：CHECK_DRIVER根在启动SDK前CWF_CREATE_ONLY创建新窗口站／桌面，显式当前用户／包SID、低MIC，只切换本进程／本线程。已有对象拒绝、不修改用户桌面；结束恢复借用的原对象、只关闭自己创建的句柄。
- 内核LPAC标志查询可能返回不支持，1510包严格True判断因此退出；现复用原Guard的有效权限对照，实际包SID／ALL RESTRICTED APPLICATION PACKAGES允许而ALL APPLICATION PACKAGES拒绝，仍要求低MIC、AppContainer及非提升。没有把None直接当true。
- 能力政策仅新增精确(registryRead,lpacCom)，空能力与原registryRead组合保留；单独COM、颠倒／重复／任意／网络能力均拒绝。新包策略随完整manifest固定。
- Guard正式准入另要求original_controller_private_logon_source与private_gui_namespace_and_owned_cleanup两项真实证据；旧证据不能直接使用。普通包准备不改变ready。

## 检查结果（15:23中间保存）

实际新来源模块2项通过（1.33秒），包括两个不同实际派生会话、原用户／会话／安全属性、新AuthenticationId、不可继承及重复关闭。首次因精确比较组集合拒绝，确认仅移除固定LOCAL／NTLM认证组后修正；不允许增加或任意改变组／特权。

精确政策与原Guard协议／未知收尾联合30项通过（25.61秒）。初次未以普通原生测试环境执行的政策4项被当前工具AppContainer身份拒绝，切到原生专项环境复核通过，没有修改操作者拒绝规则。

1510实际准备包manifest79441e0789c17e9723d331cc25cfb20d2e429ff3dac5c6b5e13924a9ae36e8b1、来源705e21eb8247867b2d5b7de24a227e1707f807a6249a48e573fa21af3d3a5ffe。原native走到GUI自检时因LPAC标志为None拒绝，exit1／无案例；原因及修复如上。

1516实际包manifest8969623cf78581e431b8baf20a83536e9ecbd2c8d3985493acf28cbe37ca753d、来源5c8cb50389c3a59c6af1753251ba7f1aa125512aa06a587c8c0f0afbc38e0ffd。原test_v20_real_browser_package.py实际1 passed（110.40秒）：固定资源复制及完整SHA、原Guard、真实独立LPAC／Job、真实Chromium、BEGIN／CASE_RESULT／END、退出0、输入完整性与STOP／RELEASE收尾均完成。先前GUI原型的单页只作为逐层证据，此项执行生产main及GUI恢复／关闭。

### 实际原生证据与测试角色的边界

上项浏览器／原LPAC／Job／专属结果写端真实；SYSTEM门禁、WFP安装及资源准入使用已有显式fixture。普通测试角色无新令牌赋值权限，因此测试控制者由CreateProcessWithLogonW置于真实新会话，再保持原控制者令牌启动LPAC；TaskNativeLaunch._launch_source为明确来源选择fixture。生产CheckLogonSession的实际派生和核验独立通过，但SYSTEM服务中的派生令牌赋值及正式WFP仍未执行。绝不据此生成正式准入或开启ready。

临时普通控制者全程固定可信源码，先挂起、关联测试自有Job，再运行；候选／CHECK_DRIVER仍按原创建原子关联，未将浏览器降级到普通账户。所有临时原始输出均在自动清理目录，文档只记录摘要。

## 当前继续项

共享回归正在执行；真实原生用例正在扩为同一固定矩阵：填写／选择／按键／点击、中文文本／数量／可见性、第二个新profile的localStorage隔离及明确FAILED。矩阵负例必须保留FAILED，不能把测试断言通过说成产品全部通过。

新增源／清理及准入记录超过1516来源快照，该包目前是已验证中间包，最终当前包待重新准备与核对。真实前后端SERVICE闭包、正式SYSTEM／WFP、供应方及Coding修复／报告／Git交付全链不在本项已通过范围。

一手规则：[CreateWindowStationW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createwindowstationw)、[LogonUserW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-logonuserw)、[固定Chromium能力定义](https://raw.githubusercontent.com/chromium/chromium/145.0.7632.6/sandbox/policy/win/lpac_capability.h)。本机结论以实际原令牌和原生事件为据，不能由文档存在推断通过。

## 完整页面与大资源传输（16:10收尾）

1525最终小页面矩阵及取消两场景已实际通过（237.32秒）；1543容量调整包同两场景通过（221.79秒）。矩阵含两个真实案例及六项断言，预期结果为一个PASSED、一个FAILED；第二个新profile证明localStorage隔离。取消在首个等待中的HTTP请求触发，核对原Job为空、部分结果流不能finish、退出非零及原资源释放；不是只测空闲取消。

实际应用主JS为3187049字节。先登记独立大资源传输迭代后，将响应body上限改4MiB、控制及私有SDK帧改8MiB；请求body／CasePack仍1MiB，结果帧仍128KiB，原累计输出预算不变。1543真实应用首次只有BEGIN、无完整CASE／END，等待超时，不能由小页面通过推断实际应用成功。

进一步定位到大DevTools命令突发写入：Node Writable一次发出全部32KiB分块，Python原有界写队列和关闭路径会等待。修复为同epoch／browser的严格递增write序号；Node最多一块在途，Python原写线程完成所有物理短写后，经原poll发送BROWSER_WRITTEN，SDK收到精确ACK才发下一块并完成Writable回调。错误／重复／布尔序号拒绝，不扩大队列或伪造ACK；确认仅证明物理写完成，不能代替权威CasePack结果。

最终1557-backpressure包：
- 目录：backend/distributions/windows/check-browser-20261114-1557-backpressure。
- manifest SHA256：2623659dc0f0d65eb4e12f23b7c478a29d6d6e2b6e9b15fa427c6522139b1582。
- 源SHA256：15f8d703a67e6fa54f75142352b68970679116d246949204d47a82865b23ad07。
- 837成员／397059891字节，完整只读校验通过；与当前实际application_sources重算一致。固定官方来源归档／旧锁原字节保留。

### 实际应用与后端

使用prepared-20261114-1545-browser-assets，program_ref=WALLE-BACKEND-20261114-BROWSER-ASSETS；backend-program.v1.json SHA256=479f71305f873419de79ddbc432011cdc3a16662aee8622b53b5adb5e24410ec，源SHA256=cff8923f709751f39487fc0fd22337a85f935611b0c7508f45f2544276cf8757。本轮实际重新类型检查、编译前端并冻结后端，原固定构建依赖仅装临时目录，清理后未改变项目／全局环境。它是15:45固定被测目标，晚于其快照的driver背压修复由1557独立包提供，不将该目标说成全部后端最新源。

v20_isolated_application_browser.py实际完成：五项原后端HTTP检查、前端index及资源实际SHA；1557原CHECK_DRIVER／真实LPAC／Job／固定SDK加载大JS并按“代码开发→测试验收→测试计划目录”导航，两个最终页面断言通过。内层1 passed（137.34秒）、外层1 passed（139.52秒）是同一场景，不累计为两项。包全部1795成员／265758755字节前后精确比对通过，临时新库llm_uses／code_tasks均0，独占服务停止、临时库及原始输出清理。

目标服务为明确普通自有SERVICE夹具，页面／业务API／冻结程序是真实实现，浏览器依旧实际LPAC；这不证明两个正式LPAC SERVICE或SYSTEM Guard／WFP已经部署。无用户正文修改、模型调用或用户8000／5173服务更新。

### 边界及共享回归

最终联合172 passed、1 skipped（67.13秒），包含实际新登录身份、原Job／LPAC／Guard协议／失败收尾、政策与新增正式准入缺失拒绝、3MiB转发／超4MiB及累计剩余预算拒绝、请求与结果旧限额、原根短写ACK、实际固定Node执行适配器ACK验证。唯一skip为旧的可选全局Playwright夹具未配置；上述新固定资源真实浏览器检查单独执行，不能把skip隐藏成全部验收通过。ACK专项实际固定Node将100000字节精确重构为四块，错误／布尔／重复ACK拒绝；不得以此单项替代真实应用结果。

registryRead+lpacCom的实际主LPAC边界检查：主机自有假文件／Guard私有文件的原生读、写、DACL访问均拒绝5，自己的scratch读写允许；无连接IPv4／IPv6 socket仍10013，OLE StgOpenStorage拒绝0x80030005。初次诊断用CRT异常winerror为空及错误OLE共享参数，修正为明确原生访问掩码／正确只读共享后复核；未把无效诊断当安全证明。

本批生产Ruff lint通过，backend/app507文件format检查通过；未关闭类型／格式规则。此前前端format:check与本轮真实构建／类型检查证据保留，本次未改前端源码。临时产物扫描为0 JSON／0截图；产品manifest／资源／正常业务数据保留。

### 可复核入口

从固定Python3.13.5项目根执行，原生Windows专项需普通完整测试身份，不能在工具自身的AppContainer中把拒绝改为放宽产品策略：

- python -B -m tools.windows_browser_package --verify-package <1557包绝对目录>。
- 显式WALLE_TEST_CHECK_BROWSER_PACKAGE=<1557包绝对目录>，用tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_real_browser_package.py -k "matrix or cancel" -q -s -p no:cacheprovider --basetemp <本轮临时目录>，通过tools.quality_gate.environment配置临时环境并finally stop_owned及清理。
- python -B tools/python-v20.py backend/tests/infrastructure/v20_isolated_application_browser.py --backend <1545包绝对目录> --manifest-sha256 479f71305f873419de79ddbc432011cdc3a16662aee8622b53b5adb5e24410ec --browser <1557包绝对目录>。
- 相关边界入口：test_v20_browser_write_ack.py、test_v20_pipe_sdk_boundaries.py、test_v20_browser_asset_frames.py、test_v20_browser_com_boundaries.py、test_v20_check_logon_session.py，以及原Guard／LPAC／资源协议专项；具体联合范围以实际命令为据，不重复累计专项和联合数量。

SYSTEM门禁／WFP／正式准入及新来源选择为明示测试角色。生产新会话派生和权限核验实测通过，但SYSTEM服务真正赋值派生主令牌未验证。正式OS证据、两个LPAC SERVICE、Guard专用分发、供应方与Coding修复／报告／交付仍独立待完成，ready=false，两份pending不自动合并。

## 最终收尾确认（香港16:15）

1557-backpressure当前包重新执行原矩阵及取消，2 passed、1 deselected（219.24秒），实际到达ACTUAL_ISOLATED_BROWSER_MATRIX_CHECKED与ACTUAL_ISOLATED_BROWSER_CANCEL_CLEANUP_CHECKED。内层分别109.60／106.90秒、各1 passed，属于同一两个场景，不额外累计。应用场景由前述独立实际后端检查执行，因此此处明确deselected，不把它说成未验证。前次收尾工具结果回取不可用，未采用未知结果；此次只重跑无付费／用户副作用的自有两个测试以取得明确退出0。

最终重算BE／FE原摘要与开工一致，当前application_sources摘要精确15f8d703a67e6fa54f75142352b68970679116d246949204d47a82865b23ad07，与1557来源一致；两实际manifest摘要均与前文一致。无新生产源码改动需重建。

原测试自身已核对Job为空／根退出及清理；补充只读进程核查在工具自身受限身份下CIM拒绝，改普通完整测试身份只读复核，本轮private-logon／native-browser测试进程无匹配。不停止用户进程、不据此推断用户8000／5173状态。临时输出清理和Git差异检查继续按项目规则，仅留Markdown摘要。
