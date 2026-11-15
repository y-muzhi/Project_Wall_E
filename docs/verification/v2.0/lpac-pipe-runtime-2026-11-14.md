# 隔离驱动管道兼容（2026-11-14，进行中）

香港12:08起四小时接续，HEAD28a7c9e／Git484条，正式BE／FE和Schema200/r49未改。无模型／计数、用户服务／库／Git目标写入、SYSTEM／WFP安装或扩LPAC网络能力。

## 已执行的隔离诊断

test_v20_lpac_socket_initialization.py：普通线程和线程模拟均得到WSAStartup0／未连接socket0，原本期望主进程限制可由模拟复现的假设失败，已记录并将测试更名为不代表主令牌限制，不将此结果算LPAC运行兼容。

test_v20_primary_lpac_runtime.py：原LPAC主令牌、原Job／目录／profile、显式registryRead精确校验，固定Python3.13.5实际进程的IPv4／IPv6未连接socket均WinError10013，_overlapped导入同10013；固定Node24.13.0仅fs／stdio初始化成功。三诊断3 passed／5.24秒，仅创建后立即关闭socket，无connect／bind／listen／传输；所有原句柄／进程／profile按所有权收尾。

固定Node SDK首次require在realpathSync对C盘根lstat时报EPERM。已有包闭包／LocalPathGuard拒绝所有链接，诊断改为--preserve-symlinks及--preserve-symlinks-main保留已固定原路径，不赋予盘根属性权限；Node SDK实际初始化并返回chromium，1 passed／6.99秒。没有关闭Chromium沙箱或扩大网络能力。

## 下一单元

沿固定SDK／原Python根的同步匿名管道适配，原根保留CasePack验证、步骤／断言比较及独立结果写端。Node只执行已枚举SDK操作并返回原观测／路由事件，不接收任意JS／路径／环境，不转发其stdout为权威帧。原控制转发／结果语义继续复用；此处为实施计划，尚未记实现或浏览器通过。正式OS／双SERVICE／供应方及交付仍未验收。


## 管道适配中间结果（香港12:35）

固定Python根仍执行原execute_browser／比较／结果写端，Node只提供私有数据SDK接口。新增check_driver_pipe_sdk.py／check_driver_pipe_worker.cjs，并纳入原包源快照及manifest。普通真实Chromium NAVIGATE／CLICK／VISIBLE通过；原Job终止后等待所有成员归零再清理，避免首轮临时目录Win32删除竞态。test_v20_pipe_sdk_boundaries.py与test_v20_check_case_evidence.py共26项通过（1.21秒），含旧context／无效响应／超帧／写满截止；未代替实际LPAC。

1220包失败：Windows环境键大写，过滤SystemRoot时大小写丢失引发Node CSPRNG初始化错误；环境白名单现按不区分大小写匹配。1225包manifest6066f52643b1dd51d2422005f2115c32b700dcf1eb39bbff182e7d58a070a0a5，原native首次BEGIN203字节但exit1，TemporaryDirectory因OS改写TEMP指向未物化AppContainer路径失败。1231修复包已生成、原native检查在途：根及固定worker恢复已建原scratch/temp，不创建未知目录、不扩权限。结果尚未出来，不记隔离浏览器通过。

## 12:56实际失败缩小

1231完整原native超时，临时固定bootstrap的有界faulthandler证明根停在tempfile.mkdtemp的0700创建重试，尚未调用SDK启动。主LPAC直接mkdir比较1项通过（1.91秒）：0700 WinError5，继承原私有ACL的0777成功写入／删除。原check_driver_browser使用fresh_browser_profile：随机新目录、原scratch ACL继承、一次创建失败立即未知、每用例结束清理；不修改系统或父目录ACL。新增失败立即返回和新会话清理，与边界／原比较／打包共47项通过（2.44秒）。

1244包manifest4b4b72319412c3949e72badfd060563ccceeea135aa39477f82fef0bd6ab4638，来源1aaf054d5fff8f88ba1a28a3e805292b11817354fc730c29791c4d4ef39786b4。原native越过profile创建，在SDK LAUNCH截止退出1，BEGIN203字节，无CASE_RESULT；原STOP／RELEASE及真实树复核完成。临时诊断bootstrap／worker重新计入测试manifest，明确测试角色，不改原正式准备包。

主Python→固定SDK私有管道实际往返1项通过（6秒）；初次夹具缺jsonschema失败后补齐同一原vendor／._pth，不作为产品缺依赖。固定Node异步mkdtemp实际成功，child_process.spawn在原LPAC中30秒不返回，连预设2.5秒JS timer都未执行；该组1失败／1通过（35.42秒），不记浏览器成功。

固定一手依据：[Node24.13.0 libuv pipe.c](https://raw.githubusercontent.com/nodejs/node/v24.13.0/deps/uv/src/win/pipe.c)使用全局uv管道前缀，并在创建拒绝时循环换名；[Microsoft CreateNamedPipeW](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew)列明AppContainer LOCAL命名要求。这与实际spawn卡住一致，后续还须原生命名空间对照，不把推断直接当完成。官方资源原字节保留，禁止借此扩权／普通账户降级。

## 13:12同版本官方无界面来源

原生全局命名管道WinError5／LOCAL成功的对照及原Node有界负例2项通过（8.05秒）；旧Node归档仍原字节保留。原根浏览器代理新增check_driver_browser_process.py／check_driver_browser_broker.cjs，实际匿名句柄显式继承，启动前检查固定EXE／原profile／沙箱参数，实际子进程完整LPAC／SID／提升状态与根相同后才送PID；SDK原算法／源字节未改。1302包manifest2c03c4aeee35cecd1d1033a9bdaabc2d66b9b4cea664c6d65be94e2cb78f27eb，普通实际两用例通过，26项新启动边界／原适配专项通过。原native实际Chrome PID已创建并核对身份，随后crashpad_client_win.cc:323 CreateNamedPipe WinError5；BEGIN203字节、无案例，仍失败。原Guard STOP／RELEASE完成。

固定Chromium145 Windows官方chrome/app/chrome_crash_reporter_client_win.cc SHA256 5b61556c92ca9f2fa48f260c7c80bee41e03c0387b696c993769f3561ecec681没有disable-crashpad-for-testing分支；不添加无效开关。改选同版本官方headless shell：最终URL https://storage.googleapis.com/chrome-for-testing-public/145.0.7632.6/win64/chrome-headless-shell-win64.zip，114056639字节，SHA256 839500db9e1b0865961ce8b05134ba3d3d71b82be5dec236d6c87ecd93e082cd。保存在原官方来源目录，旧Chrome归档及browser-runtime.lock.json保持原字节；当前browser-headless-runtime.lock.json明确9原归档。Python根实际不再依赖greenlet／pyee／Python Playwright包装，仅从原wheel导出固定Node SDK子树，整归档的命名空间／类型／总量仍完整验证，替代的生产async导入探针移除。新无界面实际SDK／LPAC证据待执行，不计通过。

## 13:56可行性结论：窗口站硬阻塞仍在

用户要求“先看看能不能搞，不能搞直接说”，本单元先完成有界可行性核验，不继续盲试启动开关；四小时原任务及完整交付未完成。当前机器、固定145.0.7632.6和原主LPAC令牌组合中，完整浏览器初始化仍不能运行；这不是已经证明所有隔离技术或整个项目都不可实现。

1316原native检查已结束并失败，不再在途。普通headless双案例此前通过；原LPAC的--version通过仅发生在ContentMain初始化之前，不能代替页面启动。最小原根匿名DevTools未收到Browser.getVersion回复；直接原主令牌启动时，创建方仅对自己进程设置并恢复SetErrorMode(3)抑制系统错误弹窗，实际退出0x80000003。未把该通用退出码直接解释为权限错误。

测试自有进程从创建时DEBUG_ONLY_THIS_PROCESS取得的原调试句柄／事件，定位headless本体RVA0x222ac4f的初始化失败分支：调用原BrokerServices虚表第三槽、参数Desktop=2，返回RAX=12。固定Chromium源码sandbox.h／broker_services.cc／sandbox_types.h对应CreateAlternateDesktop及SBOX_ERROR_CANNOT_CREATE_WINSTATION。只继续首次ntdll加载断点，其余真实异常按未处理交还系统，不吞掉浏览器CHECK。只读采样原自有线程／内存，不按PID附加其他进程，不注入、改内存或打二进制补丁。

随后完全按固定sandbox/win/src/window.cc核验CreateWindowStationW：名称NULL；显式复制当前窗口站DACL；先GENERIC_READ|WINSTA_CREATEDESKTOP（0x80000008），再WINSTA_READATTRIBUTES|WINSTA_CREATEDESKTOP（0xA）。普通原用户进程两项均创建并关闭成功；原主LPAC两项均WinError5。额外只对新测试对象显式授予当前实际用户SID与实际包SID、低MIC，两个最小掩码仍全部拒绝；现有用户窗口站／桌面ACL未改。当前窗口站DACL读取在两组均成功，故本次不是“未读到原安全描述符”的夹具错误。

早前具名0xf037f宽权限探针在普通用户下也失败，不能拿它证明只有LPAC会拒绝；此项诊断假设已被上述同参数对照替代。新私有ACL仍失败，说明不能继续把问题等同于前述mkdir0700丢包SID，也没有实施“新建私有桌面即可解决”的未经证实方案。

### 本单元命令与实际结果

均经本轮quality_gate的独占TemporaryDirectory和固定python-v20.py／quality_python.py执行，缓存禁用；原句柄、Job、profile及临时目录按原所有权收尾。下列pytest参数是在该统一包装内执行，不是直接使用个人Python环境：

- test_v20_primary_lpac_runtime.py -k windowstation：2 passed，2.10秒。明确是“原隔离拒绝＋普通成功”的诊断断言通过，绝不是浏览器通过。
- test_v20_driver_runtime_loading.py：4 passed，4.08秒；修改后的原调试采集保留零能力SXS失败、精确registryRead正例及私有文件拒绝，不吞首次真实CHECK。
- test_v20_pipe_sdk_boundaries.py、test_v20_browser_process_boundary.py、test_v20_browser_package_preparation.py、test_v20_check_case_evidence.py：76 passed，2.76秒。新增启动失败先停止原浏览器和停止未知时保留活动profile，未再删除活动浏览器使用的目录。
- python -m ruff check --no-cache：四个本批Python生产／准备文件通过；python -m ruff format --no-cache --check backend/app：505文件通过。
- frontend的npm run format:check：通过；前端本单元无源码修改，未重复构建或浏览器产品验收。

test_v20_primary_lpac_runtime.py中的三个headless完整初始化正例仍未通过，此次未在无相关生产修复时机械重跑；不能将只选择诊断组的绿色结果改写成整个文件通过。原native/SYSTEM/WFP的测试角色边界仍不变。

### 当前交付边界与下一步

当前源码包含失败清理修复，已超过1316准备包的来源快照；该包是本次失败复现版本，不是当前源码的新正式分发包。正式目录继续ready=false。普通环境及离线76项不能替代原LPAC浏览器。双SERVICE闭包、Guard专用分发、Coding明确修复／报告接收／Git交付完整链、正式SYSTEM／WFP和真实供应方仍未验收。

同一Windows主LPAC中直接容纳完整Chromium的当前路线受阻。继续之前需要独立评估能满足原网络／文件／结果权限约束的浏览器宿主边界与隔离架构；没有授权或实现把浏览器改普通账户运行、关闭sandbox、扩网络能力或修改用户桌面权限。可并行安排的其他开发仍存在，但不以其完成掩盖本项阻塞。

一手规则：[固定Chromium窗口站创建实现](https://raw.githubusercontent.com/chromium/chromium/145.0.7632.6/sandbox/win/src/window.cc)、[窗口站权限](https://learn.microsoft.com/en-us/windows/win32/winstation/window-station-security-and-access-rights)。失败结论来自上述本机原主令牌实际对照，范围限定为本次版本与配置。


## 15:23结论修正
13:56未区分NULL名称是在创建新对象还是打开现有对象；新CWF_CREATE_ONLY实际183证明共享命名对象已存在。独立登录会话、专用GUI及精确COM能力后，真实原LPAC浏览器及原CHECK_DRIVER完整生产main已通过。此前“需要更换隔离架构”的判断由[新核验记录](browser-private-logon-2026-11-14.md)替代；历史失败保留，不把测试角色改写成正式SYSTEM／WFP。
