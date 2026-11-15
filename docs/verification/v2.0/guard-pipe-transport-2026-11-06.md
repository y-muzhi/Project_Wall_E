# Guard本机端点、IO及帧检查（2026-11-06）

代码：未提交V2工作区；BE0.17-draft-17／FE0.16-draft-16、db20-r14及code20-r2不变。按7.3.1—.3／7.7.6及[独立实施细化](../../iterations/pending/v2.0/WALL-E.Guard本机通信实施细化_V_2.0.md)，本批只实现通信组件，不安装服务、不改变既有权限／网络、正常数据或用户服务，不调用模型。

## 实际实现

- windows_guard_pipe.py：固定本机命名空间及可信安装引用；新server首次实例／单实例／字节双工／重叠IO／拒远程，精确保护DACL与原owner。不同SID的backend仅显式数据／读属性／READ_CONTROL／同步权限，不含创建实例；同SID合并为原owner，仅用于同账户组件检查。client不创server／换实例，Identification SQOS，核对原DACL及可信Guard原进程／原程序；连接后持有原NamedPipePeerLease，不凭路径或nonce自报取得身份。
- windows_guard_pipe_io.py：原32字节OVERLAPPED、不可继承手动事件、≤65536字节分配、连接及部分读写，25ms有界观察、原取消信号；CancelIoEx只指原IO，最多1000ms另行确认完成。未知不能释放缓冲区／事件／端点，以进程内强owner保持，原连接不可复用；显式close重查原IO，只有已确认原完成才释放。不是业务请求成功／失败证明。
- guard_pipe_frames.py：4字节大端长度＋UTF8严格JSON对象，正文≤65532／整帧≤65536，按键排序确定输出；非文本键／非法Unicode／重复键／非有限数／不安全整数拒绝，深度32／节点32768。头与正文同一调用期限，坏帧、超限、半帧／超时令原流失效，不重新同步或自动重发。
- 端点、peer及IO／帧归创建线程的通信actor持有；跨线程调用在碰锁／OS前明确拒绝，原线程仍能继续原正常通信。其他线程使用原Event取消信号，不在任意线程池退出长期RLock／程序lease。源文件均同目录temp、fsync、原字节比较与os.replace保存。

## 环境与命令

普通非提升Windows／NTFS、.venv Python3.13.5、锁定Ruff0.17.3；tools.quality_gate.environment下经tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short及自动清理临时--basetemp。所有真实peer为本轮OwnedJob内隐藏短期进程，等待原句柄及完整空成员后清理。端点都是本轮随机新内核对象；测试没有变更旧对象DACL。

- 新server＋原peer首轮30通过／2失败：实际GetNamedPipeInfo还返回拒远程位，server为0x9而非0x1。只读新对象诊断证实0x9／max1及精确SD；修为核对实际0x9，client实际0x8。
- 修后server＋peer32通过，1.84秒。新IO专项9通过，1.65秒；同原进程／令牌／程序组合101通过，3.85秒。
- 新实际client／原双向IO与共用寿命抽取后，3文件31通过，2.10秒。真实不同PID的临时Guard程序、原Guard PID／创建时刻／SID／程序对象、无server时不创建、原Guard退出、缺可信注册等覆盖。
- 帧及IO／client三文件52通过，2.75秒；独立手工客户端按分片头／正文发送多字节文本，独立手工解码器读取发送帧；不是同一codec自回环。坏长度／重复JSON／半帧失效、头正文不重计期限、单原parser、容量边界、深度与出站事实类型覆盖。
- 线程归属与六文件组合88通过，4.28秒。测试将外线程碰锁作为立即失败，避免制造死锁；实际调用被拒后原actor仍以相同端点完成真实通信。
- 最终9文件：test_v20_guard_pipe_actor.py、test_v20_guard_pipe_frames.py、test_v20_windows_guard_pipe_client.py、test_v20_windows_guard_pipe_io.py、test_v20_windows_guard_pipe.py、test_v20_windows_pipe_peer.py、test_v20_windows_controller_token.py、test_v20_windows_process.py、test_v20_windows_executable_pin.py，共148通过，5.59秒。仅一条既有Starlette弃用警告。
- 最终218个app文件Ruff format、4模块lint、git diff --check通过；cleanup-test-artifacts.py --dry-run报告JSON=0／screenshots=0，本轮w2临时根0，无活动检查或待取回执。

取消向量含真实等待中的ReadFile、超时及其他线程Event；注入未能核实的完成／取消时原buffer及endpoint仍强持有，恢复核对后才释放。没有故意泄露永久句柄或保留后台测试进程。

## 官方依据及未完成边界

已核对[CreateNamedPipeW](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createnamedpipew)、[管道访问权限](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)、[GetOverlappedResultEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-getoverlappedresultex)、[CancelIoEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex)、[CreateFileW SQOS](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)；原peer依据见[前记录](native-pipe-peer-2026-11-06.md)。网络工具两次403技术失败后，直接仅读官方页面并在内存核对，没有存原HTML或下载执行内容。

这些是原生通信组件。临时Guard为同账户、固定Python测试程序，其脚本／依赖并非已准入的保护运行包，不是已安装生产服务，也未证明跨用户ACL生效、实际远程SMB拒绝或LPAC-WFP隔离。当前尚无七类Guard动作严格decoder／owner_epoch和原操作作用域绑定、完整后端认证接收／固定命令派发、原Registry资源池及生产入口。Guard不读业务SQLite，runtime_admitted／ready仍false；没有新增HTTP或浏览器证据，V2实际业务HTTP仍19条。
