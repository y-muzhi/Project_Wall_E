# 完整浏览器运行包（2026-11-13香港22:52起，进行中）

本轮一小时接续，范围见pending《完整浏览器运行包准备迭代V1》。正式BE／FE摘要及Schema200/r49未变，Git起始478条，HEAD28a7c9e；未动用户服务／数据库／Git目标，无模型或计数调用。

## 来源及准备

固定官方Playwright1.58.0 wheel的browsers.json声明Chromium revision1208／Chrome for Testing145.0.7632.6，注册源码cftUrl给出官方CDN。实际下载从cdn.playwright.dev重定向到Google官方storage.googleapis.com，归档181196793字节，SHA256 08476e6fe550ccbc0d11d1ab030292fc4e32d4987400c77b2d1905a6bd13b4f6。Python官方3.13.5嵌入包10903542字节，SHA256 7d2650fd9d1b9d002d4a315d5f354247fd6a44f30517c7ef577b08f57a0fb6d9。SHA为本轮对明确官方TLS来源的采用摘要，不冒充额外厂商签名验证。

Playwright／greenlet3.1.1／pyee13.0.0／typing_extensions4.16.0及实际应用导入所需jsonschema／attrs／referencing／rpds-py／jsonschema-specifications均用官方PyPI指定版本wheel，逐个核对官方元数据SHA，不装venv或全局Python。完整11个归档来源／SHA在backend/browser-runtime.lock.json。下载产物在backend/distributions/windows的browser-sources-20261113与chromium-sources-20261113，属于正式本地准备资源，保留原字节；临时下载／解压失败清理。

tools/windows_browser_package.py使用原ContentPathIndex检查完整ZIP路径命名空间、类型、限额，使用原LockedFileSource／默认流验证归档和应用来源，专用._pth隔离导入路径，仅在新临时目录复制原应用执行器／bootstrap。原CHECK20清单和精确LPAC registryRead策略随完整包固定，无覆盖发布，不生成正式OS准入。

实际初次导入失败定位到原应用检查资源链需要jsonschema，补齐已有项目锁定版本依赖；未删除原校验或扩权。第一次诊断输出还被GBK编码覆盖，后续UTF-8工具输出得到真实异常；失败临时包均清理。

## 实际证据及边界

- check-browser-20261113-2300准备成功，manifest SHA256 150e24bb527a964b4fd3e85f87fbd42cce12ea91957e1fd426342223a3b1855a；应用来源摘要4c24670ebb8c062dc310011685d5f4fb5779ba461646a142c9baa91b0c38422b。实际专用python.exe在-I／-B下导入ctypes／ssl／greenlet／Playwright及原check_driver_browser成功。
- v20_real_browser_package_worker.py：真实固定Chrome、全新临时profile、chromium_sandbox=True，复用_driver_input／execute_browser完成NAVIGATE、CLICK、VISIBLE和完整BEGIN／CASE_RESULT／END，输出ACTUAL_CHROMIUM_CASE_PASSED。原OwnedJob限制64进程／2GiB，测试原挂起根恢复后执行，finally结束本轮Job；HTML为明确夹具，不是实际产品服务。临时目录自动清理，无截图／录像／原始JSON报告。
- 原CHECK_DRIVER Guard／真实LPAC／专属结果管道的完整Chromium场景在途；SYSTEM／WFP仍明确测试角色，不预先记通过。
- 归档边界首轮9 passed／5 failed，5失败是测试预期误写RuntimeError，程序实际以原ContentPathError拒绝所有非法路径；修正测试预期，未改原路径算法。最终结果待追加。

## 23:22新增证据与修复

- 归档／源lock14项通过；连同原Git／实际清单／workspace、LPAC策略及专属管道共76项9.62秒通过。范围有重叠，不累计总数。三个受影响生产模块Ruff lint通过，backend/app及工具504文件format通过；工具局部导入排序另修正后复查。
- 2305包首次原生实际错误为CONTENT_FULL_PATH_TOO_LONG；改用短测试根，生产240 UTF-16单元限制不变。普通检查子进程缺SystemDrive导致Chrome在本轮准备包中创建五个%SystemDrive%空目录；核对均为本轮路径、无文件／无链接后逐级rmdir移除，正式文件原字节未改；测试环境补齐私有home／appdata／programdata和真实系统盘。
- 普通真实页面检查初次出现测试工具backend变量遗漏、随后诊断源转义错误；均是新检查器实现问题，已补传参、预先compile并修复转义，不改产品结果掩盖失败。
- 获取到真实浏览器控制台：WALL-E application initialization failed，crypto.randomUUID is not a function，原虚拟HTTP o1.walle-check.invalid非安全上下文。check_driver_browser.py内部受控origin改为各自oN.localhost，沿原全量route与固定alias，不改浏览器保护／候选前端。新2319包manifest 79d09ca07962352bf7829cf3829e04fd7b22e567736a28e1f4e74cfd76298468，普通OwnedJob＋实际1830冻结后台EXE＋独占新库的首页→测试验收→测试计划资源、原受控可见性断言及完整三帧通过，HTTP5项通过，库llm_uses／code_tasks均0。所有GET逐次核对原服务PID；该证据不等同两个正式SERVICE／LPAC或SYSTEM／WFP。
- 原生有界计时：来源全量扫描11.734秒，1000文件复制到38.359秒，第二次来源扫描结束45.694秒，runtime复扫到66.719秒，再次runtime复扫91.321秒超过原90秒。未到Chromium启动，不归因浏览器不兼容。真实资源测试的OS准入角色明确只返回夹具证据；原BrowserDriverProgram仍完整持有／校验源闭包及实际复制和runtime；不能宣称正式生产准入路径通过。
- 已消除扫描器和驱动复制中LockedFileSource构造后__enter__的重复读取；构造本身完整读取并校验身份／长度，拒写／替换租约保持，consume_verified／每次全量复扫及custody保留，未缓存字节验证结论。原生重查在途session46435，不能提前计通过。

## 23:36当前检查状态

完整源扫描读取优化后76项已通过；准备包完整性／显式句柄上限／即时取消与持久STOP及原workspace共26项4.16秒通过。原捕获整文件组合240秒超时，已停止本轮原树，不记整体通过；改查真实受影响的changed-and-extra和file-blocks-directory两个完整捕获场景，2 passed／77.73秒。

原生PREPARE最终已在原单次90秒内完成（最近65.38秒），CREATE_SUSPENDED前运行输入扫描仍89.72秒超时。已有改动保持每次原字节核验；只读检查复用既有100ms持久检查，补充“间隔从实际持久检查结束计算”的慢检查边界。实际CreateProcess、LPAC权限、原journal dispatch及回执仍执行原即时checkpoint；未节流副作用或放宽90秒。

完整浏览器的只读启动租约显式上限32768；其余任务／候选保持4096，非法布尔／负数／越界及失败无泄漏已专项核对。这是限额内保留原NTFS句柄，未将持有改成事后hash。原生完整场景仍在途，不把阶段推进记为Chromium在LPAC成功。

新增--verify-package只读重核真实完整文件／目录集合、每个长度／SHA、原RegisteredBrowserDriver三成员与能力／固定策略、实际解释器PE，不制造OS准入；构建发布前也复用该核对。完整清单不允许额外空目录，同长度原文件篡改被拒绝。合成PE专项仅为结构测试，真实包另外验证。

## 23:45最终准备包与只读实际联通

最终后台／当前前端包prepared-20261113-2341：manifest d34d42185758488ea89c162654c46e420bc5b275fc427f536cfba39985c069a3，来源8217129def6dc0b7cce1a75737294936faa251d17eda742cbc9de0da6b95c907，1789成员／265667878字节；真实EXE资源探针通过。

最终完整浏览器check-browser-20261113-2341：manifest 257b6eaf96915a26130bfd2e9991503574cd82f30b7d4e3b403ed1be090fd8f0，应用来源7007a4603090167adb8d426294093c6653a40ce5cc323d295242ab183e05df40；--verify-package实际1030文件（含manifest）／542295696字节、完整目录／原闭包／PE通过。旧包和原始归档均保留。

两份最终包使用新临时库／随机端口／原PID进行了实际固定浏览器导航、点击、可见性断言及完整三帧，ACTUAL_CHROMIUM_CASE_PASSED；首页与JS的SHA、三个API共5HTTP项通过。执行后llm_uses=0／code_tasks=0，服务、Job及临时库按所有权结束，无用户服务／正文／模型调用。这是当前实际普通Job浏览器联通，不是正式SYSTEM／WFP／双SERVICE全链。

原两种原生协议场景和新增专项最终24 passed／47.75秒，完整创建读回调最后补齐后生产lint／504文件format及git diff --check通过。之前完整原生已完成创建／运行／停止／释放观测，但新检查器第二次申领错误输出读端失败；已改从原唯一reader保留有界stderr，复查session15913在途，未提前宣布真实LPAC浏览器通过。

## 23:46最终原生结果（未通过，保留）

唯一reader诊断修复后，原生场景完成真实完整源物化、LPAC／Job／专属管道、CREATE_SUSPENDED／RESUME、原根退出及STOP／RELEASE和收尾核对；最终进程exit_code=1、terminated=False、权威结果帧0。真实stderr显示：driver.py→原check_driver_browser.main→playwright.sync_api→asyncio→asyncio/windows_events.py第8行导入阶段PermissionError [WinError 10013]。这是实际隔离运行依赖初始化拒绝，不是仍卡PREPARE，也不是完整Chromium已启动／通过；本轮没有取得正式SYSTEM／WFP证据，不通过增加网络能力或关闭隔离绕过。

下一步从固定Python3.13.5 stdlib的asyncio/windows_events.py和_overlapped原生扩展初始化、原LPAC精确令牌能力及默认拒绝网络机制诊断，先核实具体拒绝事件，不能仅由10013推断需internetClient或扩大权限。普通Job实际页面成功与这个失败分开保留。最后一次原生结果为失败，不计在通过数中；测试代码不skip／吞掉该失败。

当前所有本轮构建／HTTP／原生／专项已结束，最终浏览器应用来源摘要与当前源码实际重读一致（7007a4603090167adb8d426294093c6653a40ce5cc323d295242ab183e05df40）。原记录的在途状态均已由本节替代。

23:49补充：最终backend1789成员全部长度／SHA／文件集合及当前来源摘要复核通过；用户8000／5173两服务保持原PID，本轮进程筛选0。固定[CPython3.13.5 Modules/overlapped.c](https://raw.githubusercontent.com/python/cpython/v3.13.5/Modules/overlapped.c)的overlapped_exec调用initialize_function_pointers，后者创建AF_INET／SOCK_STREAM socket以取Winsock函数指针。它不等于连接外部服务；当前10013与此初始化路径一致是推断，下一次须实际事件核实。未扩大LPAC能力或WFP许可。

23:51固定嵌入产物只含asyncio/windows_events.pyc／proactor_events.pyc，按.py读取的初次路径检查失败不计运行失败；核对3.13.5 magic后仅marshal／dis解析未执行，确认行8的_overlapped导入和_make_self_pipe对socketpair的引用。该实际产物事实说明后续还需核实异步事件循环内部机制，不能只跳过一次导入或给网络能力就称验收完成。
