# V2.01 远程开发链路验证

日期：2026-11-15；登录接续核对：2026-11-16（Asia/Hong_Kong）。状态：Mac与Linux虚拟机的SSH、远程文件修改、新建SSH连接后的文件读取及Windows浏览器访问已通过；Linux Codex CLI已安装且被桌面客户端识别，客户端已进入远端账号登录阶段。可选Codex原生远程项目登录受服务地区限制，未通过；该结果不作为WALL-E内部OpenCode／国内模型通道的失败，也不阻塞普通SSH开发接入。本轮OpenCode离线原型、国内入口基础连通及固定SQLite／Linux文件保护基础原型已完成；产品启动仍需正式运行包及调用方适配。

## 范围与现场

- 依据：独立架构选型评审修订1.12的第9.3节及P0／P1前置原型；资源输入根据本轮现场更新。用户要求先验证Windows Codex到Mac Linux虚拟机的实际操作链路。
- 初始验证Git HEAD：`28a7c9e13c73a9d386081a6dd894244b51746a45`；11月16日接续现场HEAD为`a0f40592702cb702ed928849ac540479c22c224f`，本轮不据此重验产品功能。工作区含现有未提交修改，不是冻结候选。本轮未修改产品源码、业务数据或服务，已创建隔离链路验证虚拟机；未迁移WALL-E产品、调用产品模型或提交推送。
- Windows：当前项目仍在本地，项目列表初检没有远程项目。`ssh -V`为OpenSSH_for_Windows_9.5p2；`codex --version`为0.169.0-alpha.11.1，伴随本地临时目录权限警告，不据此判断远程运行能力。
- Mac已通过SSH核对：macOS26.3，构建25D5087f（用户说明为beta）；ARM64、MacBookPro18,1、10核、16GB内存。`df -h /System/Volumes/Data`报告总容量460GiB、使用306GiB、可用133GiB；后续按实测可用容量规划，不沿用此前约500GB可用的估计。
- Mac用户已完成Multipass安装，CLI和服务均为1.17.1+mac；初始无实例，本轮创建了walle-link-check。Mac本机未安装Codex，CLI安装在Linux虚拟机中。免交互sudo检查返回需要密码。`pmset -g custom`显示接电与电池模式均含1分钟系统休眠；未修改电源设置，长期在线仍待验证。

## 已执行检查与结果

| 检查 | 方法 | 实际结果 |
| --- | --- | --- |
| TCP与SSH服务 | 对用户指定主机22端口限时连接并读取服务标识 | 默认执行环境拒绝套接字；获准局域网访问后连接成功，服务标识OpenSSH_10.0 |
| 主机身份 | Windows SSH握手指纹与用户从Mac本机返回的ED25519主机指纹比对；Git自带ssh-keyscan取得公钥后独立计算SHA256并再次比较 | 一致，已固定Windows用户`.ssh/known_hosts`；严格身份检查保持开启 |
| 连接配置与登录 | Windows专用ED25519密钥；用户已在Mac添加公钥；`ssh -o BatchMode=yes -o ConnectTimeout=8 walle-mac <只读检查>` | 登录成功，执行`sw_vers`、`uname -m`、`id -un`、`sysctl`、`df`等，远端退出码0 |
| SSH扫描兼容问题 | Windows自带ssh-keyscan与Git自带扫描工具对照 | 前者报告不支持协商的KEX；后者取得公钥，校验后固定主机身份。普通Windows SSH登录正常，未改服务端算法 |
| 安装包来源 | Canonical GitHub官方v1.17.1发布API | 稳定版，2026-11-13发布；官方快捷下载链接仍指向1.17.0，本轮固定选择1.17.1 |
| 安装包完整性 | Windows下载后校验长度及SHA256，SCP传入Mac后再次计算SHA256 | 162671803字节；两端摘要均与官方发布资产摘要一致 |
| 安装包签名 | Mac执行`pkgutil --check-signature`及`spctl --assess --type install --verbose=2` | Canonical Group Limited（X4QN7LTP59）签名，Apple公证受信，系统安装评估accepted |
| 下载及临时清理 | Mac直连超时后改Windows下载再传入；核对本轮原下载进程和精确临时路径后停止并清理 | Windows传输缓存已清理；Mac旧下载进程已退出，部分下载文件已移除；准备目录只保留正式安装包 |

远端脚本通过UTF-8字节及LF换行送入SSH；首次用Windows文本模式发送时因CRLF在第一行退出，未执行准备动作，现已修正发送方式。

已核对的Mac主机指纹：`SHA256:Nybp0kgrET+tjNbAWwWfUQYFUuUEGlHORUtYFPLEfi8`。

## 现有配置与文件

- Windows连接别名：`walle-mac`，配置在用户`.ssh/config`，使用`.ssh/walle_mac_ed25519`；私钥仅保留Windows，未写入项目、输出或发送到Mac。主机记录在`.ssh/known_hosts`。连接地址与账户保留在该配置和当前会话，报告不重复记录。
- Mac安装包：`~/Downloads/walle-env-setup/multipass-1.17.1+mac-Darwin.pkg`，用户已完成安装，后续已检查实际版本及服务。
- 安装包SHA256：`d6a175c499fddf5ee787be4dc4e599b06e769a39e2c56527d56440733a1083eb`。
- 官方发布：[Canonical Multipass v1.17.1](https://github.com/canonical/multipass/releases/tag/v1.17.1)。安装候选满足官方macOS版本门槛，但不能据此宣称26.3 beta运行兼容通过。
- 虚拟机walle-link-check保持Running，2核／4GB／30GB，未挂载Mac目录；本轮临时HTTP服务、SSH页面转发及临时测试目录均已停止或清理，无仍在下载的任务。未建立WALL-E产品环境。

## Linux基础链路结果

| 检查 | 实际结果 |
| --- | --- |
| 初次镜像创建 | 从官方服务器下载到约61%时达到300秒超时；再次检查实例列表为空，没有重复创建或删除未知实例 |
| 固定镜像准备 | 从Windows下载同一份官方Ubuntu ARM64镜像，按官方SHA256SUMS校验，再传到Mac复验；Windows临时副本已清理 |
| 本地镜像创建 | Multipass使用已校验file://镜像成功创建walle-link-check；cloud-init状态done，QEMU驱动，Ubuntu24.04.5 LTS，内核6.8.0-147-generic，aarch64 |
| Windows到Linux | 配置walle-linux，通过ProxyJump walle-mac；从已认证Mac读取VM公钥并固定身份，BatchMode登录退出码0，实际用户ubuntu、目录/home/ubuntu |
| 远程文件修改 | 在Linux专属临时目录原子写入页面，Windows通过SSH把版本1改为版本2；新建SSH会话读取的文件摘要与修改结果一致 |
| 页面与交互 | Linux只监听127.0.0.1:18761，通过只绑定Windows本机的SSH转发访问；Windows内嵌浏览器实际打开页面并点击按钮，观察到交互成功；刷新后显示Linux修改后的版本2 |
| 自动核对 | 从临时环境接口确认Linux/aarch64，核对远端文件SHA256与Windows HTTP响应字节一致；这是基础链路检查，不是WALL-E产品测试 |
| 临时清理 | 通过本轮停止入口关闭HTTP服务，SSH转发会话正常退出，/tmp/walle-chain-ych0pdj3已删除；未保存截图、原始日志或JSON报告 |
| Codex安装 | 官方npm平台包0.169.0-alpha.11.1-linux-arm64，SHA512与发布元数据一致；安装完整平台运行目录并在/usr/local/bin提供入口，版本与Windows一致；普通SSH与bash -lc均可执行codex --version，app-server --help正常 |
| Codex账号 | 11月16日普通浏览器登录的回调已到达Linux，CLI在兑换登录凭据时明确返回403 Forbidden及Country, region, or territory not supported；用户页面与CLI输出一致，错误码token_exchange_failed。随后login status仍为Not logged in；本次失败原因已明确到服务地区拒绝，不再按CLI未安装或SSH故障处理 |
| 客户端入口 | 用户已添加并选择walle-linux；最新截图显示该连接为“你当前未登录”，Linux现场有客户端启动的app-server／proxy进程，证明CLI识别及远端服务启动已推进。walle-mac单独显示未安装CLI，与Linux登录问题分开 |
| 浏览器登录准备 | 官方普通登录配合SSH转发127.0.0.1:1455；首次浏览器页面打开失败，Windows等待超时后检查到远端登录进程仍存活，已核对命令后只结束该进程。首次用户报告浏览器登录成功后，11月16日复核原1200秒等待已以124超时退出；Linux仍Not logged in，默认凭据文件不存在，两端1455监听已退出。由此不能将浏览器登录当作远端CLI登录完成。核对无冲突后重新启动最长3600秒的登录；这次收到回调后因服务地区限制失败。Linux登录进程、回调监听及Windows临时转发均已退出，工具会话14871结束码1；未读取、复制或记录账号凭据 |

普通SSH会话重新建立后文件保留已验证；Wi-Fi中断、Mac休眠／重启、Linux重启和长任务恢复未验证。浏览器运行在Windows内嵌浏览器中，尚未验证Linux内的浏览器自动化，也未执行Codex模型任务或产品检查。

## Linux配置及保留输入

- Linux连接别名：`walle-linux`，地址由Windows用户`.ssh/config`维护，使用`ProxyJump walle-mac`；主机身份别名walle-link-check，指纹`SHA256:+fAJcLQPaH5LpS9g1hTkxjuF9FcCVdArl8OY9Q94/U0`。若VM重建或地址变化，必须重新通过已认证Mac核对身份，不关闭校验。
- Linux用于客户端接入的空目录：`/home/ubuntu/projects/walle-connection-check`；未复制WALL-E源码或业务数据。
- Linux Codex安装根：`/home/ubuntu/.local/share/walle-dev-tools/codex/0.169.0-alpha.11.1`；入口`/usr/local/bin/codex`指向其bin/codex，完整保留平台资源。未安装Node或项目依赖，未复制Windows登录凭据。
- 初始化配置：Mac的`~/Downloads/walle-env-setup/walle-link-check.cloud-init.yaml`，只含公钥及首次启动配置，不含私钥／密码。
- 固定镜像：Mac的`~/walle-env-setup/ubuntu-24.04-20261017-arm64.img`，616522752字节，SHA256 `50e24e1fb79e89116e939d90aa7738f7af48c442fa1bc2510131e0b39c50348e`；来源为官方release-20261017目录，Multipass报告相同image_hash。
- Codex安装输入：Mac的`~/walle-env-setup/codex-0.169.0-alpha.11.1-linux-arm64.tgz`，171822314字节，官方npm SHA512 `eewfTAE1aXThTj8Oxr0YqmR+BfSW2/ii/bSb+syhXWp/+THPolpFJ9VGOTwwaqE5FULw7FM0GUMlhhUtvUsuRg==`；Windows下载临时副本、Linux安装归档和解包临时目录已清理，Mac保留安装输入。

## 2026-11-16：内部执行器与Linux依赖原型

授权范围：接续用户“继续推进”，完成隔离虚拟机内的固定执行器准备、无模型费用验证与设计纠偏；未修改产品源码、正式锁文件、Windows服务或业务库。HEAD仍为`a0f40592702cb702ed928849ac540479c22c224f`。本批已读选型评审相关平台／P0—P2章节，以及模型配置、OpenCode协议、运行包、应用入口、数据库运行库和路径保护实现；尚未逐条重审全部Coding／Testing设计，不据此实施产品适配。

| 项目 | 方法与实际结果 | 证据边界 |
| --- | --- | --- |
| Linux现场 | Python3.12.3、Git2.43.0；内存3901MiB，可用约3537MiB，无swap；磁盘可用约26GiB；Node／npm／Docker／runsc未安装 | 现场余量不是完整任务容量 |
| 国内模型入口 | Linux解析`ark.cn-beijing.volces.com`，TLS1.3并通过证书验证；无Authorization执行`GET /api/v3/models`返回401，约0.13秒 | 无密钥、无生成／计数请求；只证明网络和认证入口可达，不证明模型权限、工具协议或效果 |
| 固定执行器下载 | 官方GitHub v1.19.5 Linux ARM64非musl包；Windows下载按官方SHA256校验，SCP传入Linux再复验，ELF机器类型AArch64 | 非musl包适用于本轮Ubuntu；未验证Linux x86_64；没有声明签名／构建可复现验证通过 |
| CLI | 在独立HOME／XDG临时目录运行固定路径`opencode --version`、`opencode serve --help`，退出码均0，版本1.19.5 | 固定版本CLI显示默认port为0，实际原型显式使用18762；不照抄最新官网默认值 |
| 服务健康与认证 | 独立网络命名空间只有回环、无外网路由；以ubuntu身份启动`opencode serve --hostname 127.0.0.1 --port 18762`，随机临时Basic密码，健康200且版本正确，无凭据/session返回401 | 只隔离本次网络；不是gVisor或产品任务文件／进程安全验收 |
| 协议和空会话 | 从源码AST取`REQUIRED_OPERATIONS`17项，实时`GET /doc`均有路径／方法／预期状态声明；POST空session、GET详情／空messages、POST空闲abort、DELETE该session通过 | 17项仅核对接口声明；没发prompt、没执行工具，空闲abort不等于在途取消通过 |
| 内存 | 首轮空服务观察VmRSS367432KiB、VmHWM375240KiB | 非压力测试、非完整任务峰值 |
| 验证脚本修正 | 首次检查主体通过，收尾直接bind端口因地址占用失败；改查实际监听。第二次冷启动读取超时，改为90秒总时限与3秒单次健康等待；中间脚本拼接语法错误在执行前退出，未启动服务。最终复验3.81秒就绪，全部上述检查通过，退出码0 | 最终发现TIME_WAIT存在但LISTEN为空；不能将TIME_WAIT当作服务仍运行。重试只涉及无模型的隔离服务验证 |
| 清理 | 最终SIGTERM后进程退出-15，ss监听为空；临时目录已删除，原始日志仅内存读取后丢弃。此前失败路径也复核/tmp临时目录、18762监听及OpenCode进程均为空 | VM保持运行，已安装固定执行器保留；未停止客户端自己的Codex连接 |
| 后端依赖可得性 | 对requirements.lock的31个固定版本查询官方PyPI元数据，均有通用wheel或CPython3.13 Linux ARM64 wheel；Playwright1.58.0、greenlet3.1.1也有对应产物 | 未安装、解析完整依赖或形成Linux正式锁文件；Python3.12系统版本不冒充原3.13运行基线 |
| 前端依赖 | package-lock已包含Linux ARM64的Rolldown、TypeScript、LightningCSS包；Vite及React插件要求Node `^20.19.0 || >=22.12.0` | 未安装Node或执行Linux构建 |
| SQLite真实阻塞 | 将原sqlite_runtime模块字节在Linux内存中加载，调用activate()明确拒绝Windows x64限制，拒绝时尚未导入sqlite3；随后只在:memory:读取系统SQLite3.45.1，不匹配原3.54.1及源码身份 | 不打开业务文件，不修改准入；__main__.py在启动产品前调用该入口，因此必须先适配 |
| 其他平台边界 | windows_local_paths要求盘符路径和Win32文件API；两份浏览器清单锁定Windows wheel、嵌入式Python及win64 Chromium | 静态证据；需Linux产物和保护语义，不能替换路径后宣布通过 |

保留的安装输入及版本文件：

- Linux安装包：`/home/ubuntu/walle-env-setup/opencode-1.19.5-linux-arm64.tar.gz`，78513091字节，官方SHA256 `fae5be262d693b7c5e562856cc473e59e741772936db0c0600ac0d5ed5bd088b`；Windows传输缓存已自动清理。
- Linux可执行文件：`/home/ubuntu/.local/share/walle-dev-tools/opencode/1.19.5-linux-arm64/opencode`，211209208字节，SHA256 `dab85b46f4ea4813da5367997f99a60aab64a2118d58ebf552980e792747436c`；未修改全局PATH，未将它作为产品受信运行包准入。
- 读取基线SHA256：requirements.lock `f4a25bca4517831e0ac522e74df1796254edb5a1a1976c80d27d4047a6ef3016`；frontend/package-lock.json `cbc9f8d37f0c827937140a780ced8790b1694707dd174d8ec0df8fc8b3c09f8c`；opencode_protocol_source.py `0011266dd536cbb76f3d3070fbf15ae5c5e84ab858cb4475af0bbd8e12ba49d7`；sqlite_runtime.py `e41e3276a20f9099975e8207d763b762efea3b4fc4e9b0aaf6a4802e9784ec9c`。
- 来源：[官方固定发布资产](https://github.com/anomalyco/opencode/releases/expanded_assets/v1.19.5)、[固定版本环境开关源码](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/flag/flag.ts)、[V1服务协议说明](https://opencode.ai/v1/docs/server/)、官方PyPI逐版本JSON元数据。原型使用无凭据的最小环境、禁用自动更新／模型目录获取／项目配置／外部插件；未验证完整产品插件运行包。

## 2026-11-16：固定SQLite与Linux文件保护原型

范围：接续用户“继续推进”；在专用VM内准备编译工具和隔离原型，所有数据库和权限场景均为本轮新建临时对象，不接入产品启动、业务库或真实模型。源码阅读覆盖sqlite_runtime、schema_v20_release、process_lock、windows_local_paths、数据库／Schema初始化和维护相关调用，以及V2.0后端7.1的数据维护规则。完整产品适配和全部Coding／Testing调用点仍未实施。

| 检查 | 实际结果及边界 |
| --- | --- |
| 重联 | 最初walle-linux握手超时，随后Mac TCP22也超时；用户确认Mac已唤醒、网络未变后，原严格身份校验和ProxyJump配置直接恢复，Linux命令退出0。未修改IP、SSH或电源设置；不能据此断言此前一定由休眠造成，也不是完整休眠恢复验收 |
| Linux现场 | ARM64、Python3.12.3，/home/ubuntu位于ext4；内存3901MiB、可用约3551MiB，磁盘余26GiB。初检gcc／make／readelf／pkg-config均无入口；libc6-dev已安装 |
| 编译工具 | 首次模拟同时指定gcc与libc6-dev会升级6个系统包，未执行；改为仅安装gcc且--no-upgrade，模拟及实际均为29个新包、0升级。安装退出0，needrestart报告无服务需重启；未修改系统SQLite或Python |
| 固定源码 | Windows从SQLite官方2026目录获取3.54.1 amalgamation，归档及sqlite3.c分别核对官方SHA3-256；内存传入Linux后再次校验，仅提取固定两个源文件到临时构建目录 |
| 原生构建 | GCC13.3.0编译ELF64 AArch64共享库，固定SONAME libsqlite3.so.0；产物校验和功能检查通过后改为0555并移到专属版本目录，不放入系统搜索路径 |
| 实际Python绑定 | 独立/usr/bin/python3 -I子进程使用仅本子进程的LD_LIBRARY_PATH；/proc/self/maps中唯一libsqlite3路径为原型库，sqlite_version=3.54.1、source_id与Windows固定源码身份一致、threadsafety=3。_sqlite3来自系统Python3.12，不能冒充3.13准入 |
| 数据库能力 | 临时库外键与STRICT拒绝非法数据、JSON、synchronous=FULL、显式事务／savepoint回滚通过；WAL下长读事务保留旧快照，提交后新快照可见；第二写进程得到SQLITE_BUSY；另一个写进程未提交即退出41，重读无该行；Backup API及两份库独立重开均66行、integrity_check=ok、foreign_key_check为空 |
| 编译差异 | Linux原型MAX_TRIGGER_DEPTH=1000，原Windows包=100；两包附带可选扩展也不同。当前静态业务搜索未发现load_extension／FTS5／RTree调用，不等于全部未来项目不需要它们。正式构建须核对并固定限值与实际必需能力，本原型不是等价生产运行包 |
| 路径边界 | 临时原型使用内核openat2、BENEATH／NO_SYMLINKS／NO_MAGICLINKS／NO_XDEV及实际fstat检查。正常普通文件通过；父目录越界、绝对路径、祖先／末端符号链接、多硬链接、FIFO、跨挂载均拒绝。跨挂载与越界内核返回EXDEV，祖先链接ELOOP；末端O_PATH链接由类型检查拒绝 |
| 权限与发布 | ubuntu持有0700私有目录、0600文件，以实际不同UID的nobody进程尝试读取／改名均PermissionError。同目录renameat2(RENAME_NOREPLACE)发布和父目录fsync通过；目标已存在时EEXIST、原内容保留。只覆盖该临时权限组合，未验证产品ACL／容器身份映射 |
| Windows保护不可直译 | 持有目录fd时，同UID写入者仍可改名目录，旧fd指向旧目录而原路径inode已改变。持有flock时第二进程原先被阻塞；改名锁文件并重建原路径后，第二进程取得新锁。由此要求保护父目录、稳定锁对象和实际身份，不能仅靠fd／flock |
| SQLite原始文件检查风险 | 全新DELETE模式临时库BEGIN EXCLUSIVE阻止其他进程SELECT；同进程对数据库执行额外os.open／os.close后，另进程SELECT成功，复现POSIX锁释放。目录fd开关及os.stat对照仍保持SQLITE_BUSY；子进程只读，未尝试破坏数据库。该结果不是WAL所有锁行为的全面结论 |
| 清理及系统对照 | 两轮数据库目录、路径权限目录、构建源目录均经finally／TemporaryDirectory清理并确认不存在，工具退出码0；无临时服务或后台任务。独立无LD_LIBRARY_PATH的Python进程仍读到系统SQLite3.45.1。原始SQL／输出／测试脚本仅内存传递，无测试JSON、日志或截图留存 |

保留输入及可重现构建参数：

- 官方来源：[SQLite3.54.1下载清单](https://sqlite.org/download.html)、[固定版本源码身份](https://sqlite.org/releaselog/3_54_1.html)、[编译选项](https://sqlite.org/compile.html)。
- Linux安装输入：`/home/ubuntu/walle-env-setup/sqlite-amalgamation-3540100.zip`，2990966字节，SHA3-256 `92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30`；sqlite3.c为9582521字节，SHA3-256 `e2b869d3003b33c942b7dd7063604fbc53553e1b66609570df39b9b7b558ee81`。
- 原型库：`/home/ubuntu/.local/share/walle-dev-tools/sqlite/3.54.1-linux-arm64-prototype/libsqlite3.so.0`，1213560字节，SHA256 `7bf5097f09e832cfbde73f7eda3c3559113348d991af18b1fd24bcbd77a4d651`。目录仍由原型用户管理，不是生产受信包。
- 编译命令：`gcc -shared -fPIC -O2 -DSQLITE_THREADSAFE=1 -DSQLITE_ENABLE_COLUMN_METADATA -Wl,-soname,libsqlite3.so.0 -o <原型库> <已校验sqlite3.c> -lpthread -ldl -lm`。GCC包gcc-13-aarch64-linux-gnu为13.3.0-6ubuntu2~24.04.1，binutils为2.42-4ubuntu2.10；libc6及libc6-dev仍为2.39-0ubuntu8.9。
- Python绑定：`/usr/lib/python3.12/lib-dynload/_sqlite3.cpython-312-aarch64-linux-gnu.so`，SHA256 `3ac40c89f5383826d425ac11272a7e6a688fbeb23860e268e8cec029a3e02c88`。原型没有安装／替换Python3.13；Node、产品依赖、Docker和runsc未在本批安装。
- Windows现有DLL在独立进程通过ctypes只读查询版本、源码身份及compile_options，没有打开任何数据库；据此发现触发器深度差异。产品SQLite准入和Schema清单未修改。
- 路径原型依据：[openat2](https://man7.org/linux/man-pages/man2/openat2.2.html)、[rename](https://man7.org/linux/man-pages/man2/rename.2.html)、[flock](https://man7.org/linux/man-pages/man2/flock.2.html)；SQLite文件风险及对照依据：[官方锁与文件约束](https://sqlite.org/howtocorrupt.html)。仅把本轮真实结果列为原型证据，不声称完整文件保护或产品安全验收通过。

## 2026-11-16：Python3.13固定绑定、依赖与前端构建

本批继续隔离原型和接入设计；HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。未修改产品源码／正式资源／锁文件，未启动WALL-E、复制业务库或调用模型；原型产物留在Linux专用工具目录，测试环境全部临时创建。

| 项目 | 实际结果与边界 |
| --- | --- |
| 编译依赖 | 先模拟，再仅安装明确的构建依赖；16个新包，liblzma5／xz-utils从5.6.1+really5.4.5-1ubuntu0.3更新至0.4，zlib1g从1:1.3.dfsg-3.1ubuntu2.2更新至2.3。脚本拒绝其他升级／移除；libc6与系统Python未替换 |
| 系统服务 | NEEDRESTART_MODE=l，未主动重启服务。needrestart列出SSH、网络、日志等进程仍使用旧库，需要后续维护时重启；本轮不能声称已验证VM重启后的状态。现有SSH连接正常，未停止客户端Codex进程 |
| Python来源 | 官方Python3.13.18源归档，2026-10-25发布；Windows下载和Linux接收均按官方SHA256验证，23243936字节。仅解包到自动清理的构建目录，不安装到/usr或改全局PATH |
| 首次构建失败及修正 | 初次编译完成但缺_sqlite3，关键模块检查立即失败，未发布候选，临时目录清理。只读诊断脚本一次文本定位失败，未改变环境；修正构建期libsqlite3.so链接入口后，头文件、11项SQLite符号及py_cv_module__sqlite3=yes检查通过。链接仅在构建目录存在，发布前移除 |
| 固定Python候选 | GCC13.3.0构建CPython3.13.18，--with-ensurepip=install、--disable-test-modules、make -j2／altinstall DESTDIR；未启用PGO或free-threaded。SQLite编译另显式加SQLITE_MAX_TRIGGER_DEPTH=100，保持THREADSAFE=1及COLUMN_METADATA。_tkinter为缺失可选模块，不用本包运行桌面GUI |
| 实际绑定 | _sqlite3的ELF RUNPATH固定到候选自身lib，NEEDED为libsqlite3.so.0；最终目录中以全新干净环境运行，不设LD_LIBRARY_PATH／LD_PRELOAD，进程映射只出现候选私有SQLite，版本／源码身份正确，触发器深度100。pip26.2.2可用；此路径为当前原型固定路径，移到/opt等位置须重新构建验证 |
| Python3.13数据库专项 | 复用上批临时数据库场景，在新解释器及新库上验证实际绑定、外键／STRICT／JSON、FULL同步、事务／savepoint、WAL读快照、独立进程写锁、未提交进程退出、Backup API和重开，全部通过 |
| 后端依赖 | 独立临时venv，读取原requirements.lock，以--only-binary=:all:安装；31项精确版本全匹配，除venv自带pip无额外包，pip check通过。FastAPI／Uvicorn／JSON Schema／HTTPX／Markdown／Pydantic Core／rpds及SSL、压缩、ctypes导入通过；未导入或启动完整产品服务 |
| 下载边界 | 后端安装约221.77秒；一次下载连接中断，pip执行了一次不完整下载续传后成功。--retries=0不等于关闭独立的断点续传机制；此次仅为包下载，不是模型／计数重试。未生成带产物hash的Linux正式依赖锁 |
| Node候选 | 官方24.22.3 LTS Linux ARM64归档，两端SHA256验证，独立版本目录安装；node --version=v24.22.3，npm=11.19.1。未替换系统命令入口 |
| 前端准备修正 | 初次npm因用户／全局配置同指/dev/null而拒绝；改为不同临时空配置。随后两次类型检查暴露验证输入未带shared及backend/resources，均补齐原输入，无源码修复、降级或忽略类型；据此补充构建交付边界 |
| 完整前端构建 | 同一工作区的frontend＋shared＋backend/resources共852个受版本控制文件，复制前后字节摘要一致；npm ci --ignore-scripts --no-audit --no-fund安装232包，原npm run build完成tsc --noEmit和Vite构建，退出0，dist120文件。保留原大于500kB的包告警，主JS约3187.04kB／gzip921.67kB；未浏览器验收或优化构建 |
| 实际Schema兼容 | 读取固定db20-r50清单及fresh.v1.sql／objects.v1.json，分别核对发布清单摘要与资源hash。复制未改动的database._statements及schema_inspection关联源码，在新临时库执行299条SQL，生成299对象／72表；原结构检查结果与对象清单一致，integrity／FK及重开核对通过 |
| Schema证据边界 | 只证明当前建表语句及最终结构与新库兼容；未调用产品load_release／initialize_v20、未写业务初始化来源标记、未运行Windows到Linux历史迁移或业务接口。没有取消／替换原准入保护 |
| 清理 | Python源码／构建目录、前端源码副本／node_modules／dist／npm缓存、venv／pip输入、所有临时数据库均已清理；没有留下测试JSON、截图、原始日志。安装源归档与候选运行工具保留，原项目源码仍在Windows |

固定输入、产物与可接续位置：

- Python源：/home/ubuntu/walle-env-setup/Python-3.13.18.tar.xz；SHA256 abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68。来源：[固定发布页](https://www.python.org/downloads/release/python-31318/)。
- Python候选根：/home/ubuntu/.local/share/walle-dev-tools/python/3.13.18-sqlite3541-linux-arm64。bin/python3.13为33328496字节，SHA256 e2496c69b9d71984284f35f46c459073a778e1b6d9ddaf2d4f6600090482d232；lib/python3.13/lib-dynload/_sqlite3.cpython-313-aarch64-linux-gnu.so为824272字节，SHA256 e8ca297502c5e9b6822b1b2855a6aa26ab1f6f799a32f517559b82eb4e165522。
- 新SQLite库：上述候选根/lib/libsqlite3.so.0，1213560字节，SHA256 3cc41af77be117b438833900ec2803b4be1a800f7e31fc409cf6237c646462c9。与上一批独立3.12原型分目录保留，正式接续采用本候选验证，不误用深度1000的旧原型。
- 构建绑定：LIBSQLITE3_CFLAGS指向已校验sqlite3.h；LIBSQLITE3_LIBS使用临时lib目录、-Wl,-rpath,<最终候选根>/lib及-l:libsqlite3.so.0；构建期另提供标准libsqlite3.so入口，发布前移除。仅构建过程使用临时LD_LIBRARY_PATH，最终运行不需要；源码不修改。实际构建还依赖本VM的GCC／binutils／开发库，未宣称跨机可复现构建或独立于系统库。
- 新增开发包版本：make4.3-4.1build2、pkg-config／pkgconf1.8.1-2build1、libssl-dev3.0.13-0ubuntu3.16、zlib1g-dev1:1.3.dfsg-3.1ubuntu2.3、libbz2-dev1.0.8-5.1ubuntu0.1、liblzma-dev5.6.1+really5.4.5-1ubuntu0.4、libffi-dev3.4.6-1build1、libreadline-dev8.2-4build1、libncurses-dev6.4+20240113-1ubuntu2.2、uuid-dev2.39.3-9ubuntu6.6、libgdbm-dev／libgdbm-compat-dev1.23-5.1build1、libdb5.3-dev5.3.28+dfsg2-7。运行SSL报告OpenSSL3.0.13，Ubuntu包libssl3t64版本3.0.13-0ubuntu3.16。
- Node源：/home/ubuntu/walle-env-setup/node-v24.22.3-linux-arm64.tar.xz，30991864字节，SHA256 6e51a2ada00f0011cc266f65d98922b403d7ad88f809ca2aa615a5fe1ce6e86c。工具根：/home/ubuntu/.local/share/walle-dev-tools/node/24.22.3-linux-arm64；bin/node为123446736字节，SHA256 8f9c2a55879e9705cb285b6cdd649d95df642c6720f052cb30f300d2677da99f。来源：[官方发布及校验和](https://nodejs.org/en/blog/release/v24.22.3)；本轮核对官方HTTPS摘要，未宣称独立签名验证通过。
- 完整前端输入树摘要：按相对项目路径排序，以路径＋NUL＋文件SHA256＋LF拼接后SHA256为c3ba0f74fbf2f94d751c3eec3968af3e81febbf6359a128c377f2c95109ef312；原requirements.lock摘要仍为f4a25bca4517831e0ac522e74df1796254edb5a1a1976c80d27d4047a6ef3016。
- db20-r50发布清单SHA256为10ff02e670eb705e6ac537eb9335449a72de9dbc93eeffbe46b16d7d74557f31；结构契约SHA256为62eeeaee0ce469548abc4b4916a39c41dd28e2040b2c88c8ff035203988540c5。原Windows发布清单与资源保持不变。

## 2026-11-16：普通业务后端契约静态设计

本批只阅读代码／设计并编写独立迭代文档，没有连接或改变Mac／Linux，没有执行新的产品验证、启动WALL-E或调用模型。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f；以下为静态设计结论，不续用上批原型作为本批端到端证据。

| 核对范围 | 发现及设计处置 |
| --- | --- |
| service／__main__／GuideWorker | 原生导入、后台任务及最终接单顺序必须显式适配；保留唯一进程锁、数据库恢复、ExecutionLease和部分启动失败收尾 |
| schema_v20_state／release／现有EnvironmentRecord | 现有来源标记与内部任务环境观察不能代表应用环境归属；后端草稿定义库内单行environment_binding及外层配置核对。此增量要求新DDL／发布清单，原db20-r50结构专项不能覆盖它 |
| 原需求与人工编辑契约 | 按V1.5创建需求、空白／框架文档、开始／保存／完成人工草稿及实际HTTP入口定义普通闭环；分别验草稿与CURRENT，不用固定成功返回 |
| 模型与执行限制 | 文档Chat／计数、Testing计划、Coding／Git／检查均需在HTTP、命令、后台及实际出口覆盖；原请求查询不能被新的能力开关抹除 |
| 前后端共同边界 | 定义环境／代次请求头、只读握手、共同拒绝码及旧请求未知判定；浏览器存储、代理认证与CSRF仍明确为联合设计缺口 |
| 文档与保护 | 新增后端迭代0.1／DRAFT；README增加唯一导航，架构1.13改为引用详细契约并纠正已完成前置依赖后的下一步。业务大纲、正式设计、源码／锁文件／冻结资源不改 |

阅读边界：完整V2.01大纲1.18；架构第6章、10—11章相关约束；统一模板总体职责与本批字段规则；V1.5需求创建／文档创建及人工草稿关联契约；V2.0后端总则、实际Schema及装配／恢复源码。没有重新声称全文复核全部V1.5／V2.0设计。

本批来源摘要：大纲SHA256 364853f1c9aea41b5a11a858c27f23d7498fb761734451d936f5b031e0ce85a6；模板SHA256 7e73b764207aac74f43b70996c2b84ce68e8233f2ccf161a95f613e653e0bc66；service.py为16e81c503d9551141b539b6e63bb29342f942ea7298a87a6879c75ed3b586dac；schema_v20_state.py为67df9a6094f7f4384da5bada8350130caefcc63ef9972226be6b323859ea37ea。

本稿范围、未完成设计及TC201-P1-01—10见[后端迭代设计](../../iterations/pending/v2.01/WALL-E.环境分离后端迭代设计_V_2.01.md)。实际检查：git diff --check退出0；5份版本文档的35条本地链接有效；新稿八章及10项验收编号齐全；6项受保护输入摘要未变。另复核配置摘要来源、能力关闭范围、原请求未知、环境元数据引起的新结构及下一步一致性。未运行产品测试、构建、浏览器或供应方检查。

## 2026-11-16：入口与浏览器隔离联合设计

本批接续后端0.1，补齐P1的联合入口及前端契约；仅静态阅读和文档维护。未连接Mac／Linux、未修改产品代码或配置、未启动服务、未运行产品测试／构建／浏览器验证、未调用模型／计数。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。

| 静态发现／审查场景 | 本批设计处理 |
| --- | --- |
| main.tsx及Router会开始业务加载，当前ApiClient没有环境作用域 | 先受信公开配置与握手，后创建不可变客户端／仓储／路由；实际响应身份再校验，迟到结果仅能属于原owner |
| 布局、阅读、对话、卡片、交接、Coding和Testing草稿的分区方式不一致 | 前端第7章逐项登记；统一session／local及history外壳，两类IndexedDB加入origin／环境／代次；原命令v5保留原key、body及CAS |
| 文档恢复键只有文档业务编号，原命令身份只有origin等原字段 | 同地址数据更换时不得自动认领旧草稿／命令；旧版本库保留原字节，只读查看／导出不派发；不同scope容量合计，避免按环境无限放大 |
| 认证通过、环境能力和用户写权限是三件事 | Caddy逐环境Basic认证；后端受保护Unix通道、身份清洗和固定权限映射；握手返回当前access，READ_ONLY不因DOCUMENT_WRITE就绪而出现可写状态 |
| Basic凭据可由浏览器自动携带，SSH不提供CSRF保护 | 固定HTTPS来源、浏览器自定义头＋Fetch Metadata＋Origin；自动化使用独立身份，类型头不自行授予权限；有副作用GET仍受实际动作限制 |
| 错API可自报身份，正常重启与换数据也容易混淆 | 配置由入口独立提供；配置／实际握手交叉核对。run_id变更不清键；代次变化暂停旧写入；401、能力关闭及新库NOT_FOUND不否认旧未知 |
| Vite开发入口可能携带用户凭据或走二次API代理 | Caddy分别路由API与Vite，认证后清洗凭据；固定Host与WSS/HMR路径，只有入口经SSH转发；需实际验无直连旁路 |
| 完成边界 | 前端0.1八章、12项TC；后端0.2扩展第5—6章及共同错误；架构1.14与README指向两份详细设计。只是这一批契约完成，P1和全V2.01均未验收 |

本批阅读边界：后端0.1全文；架构第6.4／11.4及相关用途边界；V1.5前端人工编辑／本机恢复及第7.4节关联条目，V2.0前端第7.4节相关存储／原命令规则；main、Router、ApiClient、FrozenIdentity、CommandRecoveryStore／model／owner、DraftRecoveryStore，以及前端文档第7.4节列出的现有存储／缓存调用方。未宣称重新阅读全文所有原版本规格。

来源与复用核对：官方[Caddy认证](https://caddyserver.com/docs/caddyfile/directives/basic_auth)、[反向代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、[本地HTTPS](https://caddyserver.com/docs/automatic-https)、[Vite服务选项](https://vite.dev/config/server-options)、[Uvicorn套接字配置](https://raw.githubusercontent.com/encode/uvicorn/master/docs/settings.md)、[MDN CSRF](https://developer.mozilla.org/en-US/docs/Web/Security/Attacks/CSRF)和[Fetch Metadata](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site)。仓库锁定Vite8.3.2的本机类型声明也确认server.ws；配置仍未实施，不借文档更新升级依赖。

静态检查：git diff --check退出0；6份文档的48条本地文件链接有效，前／后端各八章及12／10项TC连续且唯一，无本轮原子保存临时文件。6项既有大纲／源码／锁文件摘要未变；模板摘要记录的一字符笔误已按工作区、Git索引与HEAD三者相同的实际字节更正为7e73b764207aac74f43b70996c2b84ce68e8233f2ccf161a95f613e653e0bc66，模板未改。额外静态搜索未发现现有Service Worker／CacheStorage、window.name或document.cookie存储路径。复核了只读身份、原命令实际key字段、配额仅计pending、跨scope容量扫描、错误绑定响应、401、迟到回调、BFCache及新代次恢复；不能据此称入口、凭据或浏览器恢复已经实测。

## 2026-11-16：平台发布与新数据初始化契约

本批按“继续推进设计”完成后端0.3，并同步前端0.2、架构1.15及导航；没有增加文档种类。只进行文件／AST／资源摘要等静态读取与文档编辑，没有连接Mac／Linux、生成运行资源、执行DDL、启动服务、安装依赖或调用模型／计数。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。

| 现有依据与发现 | 最终设计处理 |
| --- | --- |
| sqlite_runtime只接受Windows DLL；tools/python-v20先导入产品运行模块 | 宿主受信入口先验运行包，目标解释器-I -B -S启动并显式加入已核验依赖；禁止site启动钩子和事后清理加载环境冒充前置准入 |
| requirements.lock为31项精确版本，无逐wheel hash | 保留原版本输入；分平台wheel清单、带hash锁、离线安装、闭包／实际导入和安装文件索引。实际hash待后续资源准备，不伪造本轮产物 |
| SchemaRelease的sqlite_runtime含dll_sha256，构造器同时做fresh／151-upgrade | 新manifest.v2显式FRESH_ONLY、upgrade_sql_ref=null；保留同一构造／检查机制，旧资源不覆盖，不能为了旧接口凑假升级脚本 |
| 新环境归属不能仅存在启动参数中 | 后端第7.6节给出单行STRICT／WITHOUT ROWID表的精确DDL；与两项原元数据同事务。73表／300对象仅为增量预期，本轮未执行验证 |
| schema_v20_publish只实现Windows不覆盖目录发布；比较旧pin后replace并非跨进程CAS | Linux使用不覆盖重命名、目录同步与发布互斥，pin最后更新；固定prefix运行包使用受保护最终位置准备，不能简单改名导致RUNPATH失效 |
| schema_v20_cli先建空文件再进入维护会话 | 改为稳定锁先于文件创建、原意图与TARGET_BOUND持久后才开SQLite；明确无归属证据空文件、提交未知、回执丢失及重复原操作边界 |
| 发布来源与循环摘要 | 保留现有39项构造来源校验并登记新增模块；运行包→文件／依赖与Schema→运行包单向关联，生成pin和manifest不自包含 |
| 批次边界 | 新增TC201-PKG-01—08，沿用10项P1及12项前端验收；格式与DDL已定义，发布资源、代码接入、真实初始化和产品闭环仍未完成 |

已读范围：本批后端0.2全文及新增条款；架构6.1—6.4与下一步；schema_v20_release／publish／state／cli／assembly／admission、sqlite_runtime、schema_inspection、tools/python-v20及requirements.lock全文；Database连接／初始化前半段、UtcTime与Schema字段关联定义；原发布manifest和39项来源集合。未重新声称阅读全文所有V1.5／V2.0规格。原publish源码SHA256为ce113e9c409321c05a8855b1aac725e07883d74bd27d48aa3382deac972c0542，release源码为e05f9888577d78a87f7d607f64b5301e82e173bc44cc3afca9c78d18c8a21b43；大纲及原发布摘要保持原记录。

官方规则已核对并在后端相应条款引用：CPython隔离／site选项、pip完整哈希模式、PyPA包名与兼容标签、SQLite严格表／WITHOUT ROWID、Linux不覆盖rename及文件／目录fsync。项目选择和外部组件已提供能力分开描述，未将资料查询当作系统实测。

实际静态检查：git diff --check退出0；6份文档49条本地链接及章节锚点有效，前后端八章结构、前端12项／后端P1十项／新增平台8项验收编号连续且唯一。13项大纲／源码／锁文件输入摘要未变；原db20-r50 manifest、3份资源及39项构造来源全部与原发布摘要一致。临时保存文件为0。复核了清单引用无自摘要循环、元数据纳入文件索引、固定prefix与资源重命名的区别、原pin并发保护、单行表初始化来源及中断恢复；只作静态核对，DDL可执行性、实际加载／目录同步及恢复结果仍待专项，不能登记为本轮产品通过。

## 2026-11-16 环境管理、交接与可视化设计

本轮接续“继续推进设计”，范围为文档及静态审阅。未连接Mac／Linux、未修改产品源码／业务库／运行资源／宿主配置，未启停服务、执行产品测试／构建／浏览器或模型／计数调用，未提交推送。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f；保留本轮开始前已有文档改动。

读取范围：大纲1.18第3—6章、后端0.3及前端0.2相关完整契约、架构第2.7、10—11章、项目约定；静态核对code_environment_records、code_tasks/operation_protocol.py、infrastructure/process_lock.py／command_receipts.py／idempotency.py及tools/ai-service.py。原内部EnvironmentRecord是任务／检查依据，原命令仓储绑定业务Schema和步骤，不宜直接作为多环境控制账本。未重新全文评审所有V1.5／V2.0设计；本轮新增边界如下。

| 发现及审阅场景 | 最终设计落点 |
| --- | --- |
| 业务停机后仍须管理；内部任务环境记录不是开发环境注册表 | 单宿主固定管理程序＋独立SQLite登记，八类最小逻辑存储，复用固定运行库及纯规则；无通用调度／流程引擎 |
| 创建可能部分成功，超时后不知道operation_id | 原键查询、原初始化子操作绑定、创建与启动分开；ATTACH不覆盖；原控制命令另有回执 |
| 启动中互斥会挡住停止，管理进程退出但辅助进程仍活着 | 原START的取消可达，明确残留启动的停止目标；实际进程组／原运行核对，不凭PID／名称或心跳释放 |
| 多请求争容量、未知结果被当空闲 | 同事务预留、环境与共享资源分别占用；容量过期阻止新增，等待需主动继续，未知不按TTL释放 |
| 交接后旧Agent仍可能改同UID文件 | 当前分配与管理权限隔离；保留脏文件，专属许可撤销失败不交接，共享UID边界及人工停写确认明确 |
| 交付引用只在待删目录／人工声明假作系统检查 | REGISTER_DELIVERY固定commit、资源／证据及未覆盖项；不触发检查／Git写入，清理前核对独立可读取性 |
| 清理预览后目标变了／删了一半 | 服务端绑定计划、有效期、逐项身份复核，已知失败与UNKNOWN分别处理；无默认全删、无父目录扩删 |
| Linux创建成功但Windows入口打不开 | 服务端认证／路由准备与Windows名称解析／证书／转发分别验；入口待准备不报PREPARED，不给匿名旁路 |
| 复用业务前端客户端或存储导致管理命令串目标 | 独立管理scope、固定管理前端／API、原动作和控制键仓储；登记换代冻结旧记录，业务标签保持原绑定 |

交付：后端0.4／DRAFT、前端0.3／DRAFT、架构1.16／REVIEW及README；大纲1.18不改，未新增过程草案。后端新增TC201-MGT-01—12、前端新增TC201-MFE-01—10，共22项待执行验收。管理物理Schema／服务模板／实际安装与故障证据、完整执行及生产维护仍未完成，不把逻辑设计当作现有控制台。

外部依据仅使用Git和systemd官方说明，具体链接在后端第7.9节；选定现场版本与实际能力仍须安装时核对。Docker Compose项目名文档本轮获取超时，未作为新增结论依据。

实际检查：git diff --check退出0；内存Python静态核对6份Markdown、50处本地链接／锚点、两份八章结构、版本及P1／PKG／FE／MGT／MFE连续唯一编号通过；13项受保护大纲／源码／锁文件摘要不变，原db20-r50 manifest、3份资源及39项来源与原发布摘要一致；无本轮临时写入文件遗留。源码静态阅读不等于管理Schema、原子占用、实际停止、认证入口、容量或浏览器验收通过。

本批文档内容摘要：后端SHA256 69aea960a80e6aa93af8e36d0e833d31251e4da7c7be2a6743f15e363608de6b；前端SHA256 87ddba52592bb2334da0c989d2f7bdfaf3a25260df895e48346a015233c8fe0a。后续修改后应以当前文件及修订为准，不将此摘要用于运行准入。

## 2026-11-16 维护、固定候选发布与恢复设计

本轮接续“继续推进设计”，仅修改待合并设计及本记录，保留既有改动。未连接Mac／Linux、未修改产品源码／数据库／运行资源／宿主配置，未启停服务，未运行产品测试／构建／浏览器／模型或计数调用，未提交推送。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f；本轮没有新运行证据。

读取范围：项目约定、大纲1.18第7—9章、架构维护／恢复与后续设计范围、后端0.4及前端0.3的相关完整对象／管理原操作／存储契约。静态阅读service.py、infrastructure/execution_lease.py、guide/worker.py及commands.py、testing/planning_worker.py、code_tasks的原命令／终止／仓库读取路径，以及schema_v20_cli.py／upgrade.py／maintenance.py／plan.py／assets.py／plan_codec.py和Database备份入口；未重新全文审查全部V1.5／V2.0设计。

| 发现及审阅场景 | 最终设计落点 |
| --- | --- |
| 当前停机时退休租约会中断落盘，HTTP停接单也不能阻止后台Testing claim | 持久DRAINING、原短事务票据与异步收尾清单；入口和后台出口共用准入，收尾后才退休租约与关闭进程 |
| Guide continue实际创建新GuideRun；部分GET会进行真实仓库快照读取 | 明确纯读取／新意图／原收尾／原取消／恢复核对分类，不按HTTP动词或“继续”名称放行 |
| 换数据目录后每库独立锁可能允许新旧实例同时写入 | 环境control_root固定，environment.lock跨恢复代次不变；在线应用与离线工具按同一锁交接 |
| 更新计划被自身收尾推进版本卡住，或配置／数据／程序只切一半 | 首次受理核对原版本，后续按原步骤CAS；影响候选或恢复依据的变更须REPLAN。部署元组固定选择，切换窗口保持CLOSED |
| 新程序启动恢复已写库，程序回退被误当作可覆盖旧数据 | SAME_SCHEMA须证据；程序回退保留当前数据。曾开放或未知是否开放均禁止自动用旧快照覆盖新内容 |
| SQLite备份未包含库外资产，上传成功被当成灾备完成 | Backup API＋完整资产封存＋Restic固定快照；LOCAL_VERIFIED与OFFHOST_VERIFIED分别有实际恢复核验要求 |
| 恢复旧数据库会复活队列、许可和旧浏览器重试 | 新数据代次、外部outbound_hold、旧原键只读核对；完整任务许可／预算核对另待设计，不设任意清除限制按钮 |
| 管理库恢复会覆盖当前维护；宿主恢复的旧OPEN可能自启 | 管理登记换代但不覆盖各环境控制事实；受信宿主recovery_hold在启动前和最终开放核对，逐环境核验后才放行 |
| 发布期间输入丢失、失败页面误显示已回滚 | 只读维护入口、原取消／结果可达、本机草稿保留；计划差异重新确认，展示实际切换／恢复状态 |

交付：后端0.5／DRAFT、前端0.4／DRAFT、架构1.17／REVIEW及README；大纲1.18保持不变。维护共用已有管理原操作与身份协议，没有新增平行管理服务。后端TC201-REL-01—15及前端TC201-RFE-01—09共24项是新增待执行验收，未执行任何产品验收。

官方依据核对SQLite Backup API／WAL及Restic准备仓库、恢复、仓库检查文档，链接保存在后端第4.12节及架构评审。Restic负责封存包存取，不替代项目资产清单、身份核验或恢复准入；具体安装二进制及摘要、云存储、保留周期与恢复目标仍未确定。现有Windows 151→200维护工具仅复用适用规则，不认定它已支持Linux发布或通用恢复。

实际检查：git diff --check退出0；内存Python静态核对6份Markdown、50处本地链接／锚点、两份八章结构、版本及P1／PKG／FE／MGT／MFE／REL／RFE连续唯一编号通过。13项受保护大纲／源码／锁文件摘要不变，原db20-r50 manifest、3份资源及39项来源与原发布摘要一致，无本轮临时写入文件遗留。上述结果仅证明文档与被保护输入的一致性，不证明并发收尾、原子切换、全资产备份、真实异机恢复或页面可用。

本批设计摘要：后端SHA256 2df68bcde2d4146611e2fbb24140149744eba9a459de5013526005cbb07318c0；前端SHA256 c9f82a0bcc61c598ba827b83eafc0996c0a646809405973b7bed89912b8ef3b3。后续修改应以当前文件及修订为准，不将此文档摘要用于运行准入。


## 2026-11-16 Linux执行生命周期与恢复用量审查

本轮仅接续设计、源码静态阅读和官方资料核对。未连接Mac／Linux、未安装Docker／runsc、未修改产品代码／Schema／数据／宿主配置，未启停服务、运行产品测试／构建／浏览器或模型／计数请求，未提交推送；保留既有文档改动。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。

读取范围：项目约定、V2.01索引／当前断点、大纲第7—8章、架构第2.6—2.7及11章相关段落、后端普通能力／管理／维护与恢复契约、前端维护与页面接入；V2.0的OBJ-CODE-USAGE、APP-CODE-MODEL及内部模型／恢复入口。静态核对task_runtime_launch／recovery、task_runtime_stop的停止证明与推进函数，coding_model_ledger的预留／发送／恢复、coding_model_admission、task_start_authorization、question／permission_response、testing/run_stop、TaskModelIngress、guard_task_model_source、authorizations.py及CountingJournal。长模块按关联函数阅读，不声明已重审全部执行代码或全部V2.0规格。

| 本次发现 | 设计处理 |
| --- | --- |
| 原模型入口校验真实OpenCode根进程；容器IP／token不等价 | 保留原强度，将离线根来源与子进程冒用对照列为P2首个门槛；gVisor监测资料仅作候选，不声称机制已解决 |
| Docker创建／启动和Windows挂起创建语义不同 | 抽取“未运行先固定身份／策略／回执”不变量；新Linux证据格式，不伪造Job／SID或继续硬绑定Windows对象 |
| 停止需先撤销网关，再abort及核对全部资源 | 沿原业务步骤，区分STOPPED／费用待核对／RELEASED；Docker默认超时强杀不用于普通维护 |
| 控制程序重启但容器仍可能运行 | restart=no，原意图／完整资源身份恢复，未知不重复启动；管理失联不使已运行任务失去停止路径 |
| 多环境各自判断空闲会突破单重任务限制 | 复用跨环境resource_claims事务分配宿主执行名额；同一环境预留的内存不重复扣减 |
| 维护把所有内部模型步骤当新工作，可能卡住原轮次 | 具体原消息／原步骤链决定收尾；新问题答复／权限决策含DENY均拒绝，已发结果可核对，原任务终止可达 |
| 授权创建依赖Windows current_operator_sid | Linux改为可信入口的实际业务principal，服务UID不冒充用户；P1 DEVELOP／管理MANAGER不自动获付费授权 |
| 恢复旧库会让原NOT_SENT／旧余额倒退 | 外层原外发证据与当前账联合核对；旧快照不能套同代次recover_interrupted_calls，不明费用不记0、不重发 |
| CountingJournal检查旧数据库锁路径 | 平台适配须一起核对稳定control_root锁和数据身份，不能仅改锁路径或禁用原检查 |

交付：后端0.6／DRAFT、前端0.5／DRAFT、架构1.18／REVIEW及README；大纲1.18保持原字节。新增后端TC201-EX-01—15与前端TC201-EFE-01—07，共22项待执行验收。执行生命周期与页面观察已定义，但根进程来源证明、精确环境许可／恢复审阅提交与存储、Linux独立检查及Git交付仍未闭合；不是完整执行已迁移或可上线。

外部依据为Docker官方安全／停止／重启文档及gVisor官方Docker接入、平台、网络、安全模型与运行监测说明，链接在后端第4.13—4.15节和架构第11.3节。源码要求与官方能力之间的差异是本轮推断与验证门槛，不能把文档中存在“monitoring”当作同步来源鉴权已可实现。本轮未实测这些组件，也未新增固定版本或产物摘要。

实际检查：git diff --check退出0；内存Python核对6份Markdown、50处本地链接／锚点、前后端八章结构／修订及全部P1／PKG／FE／MGT／MFE／REL／RFE／EX／EFE连续唯一编号通过；13项受保护输入摘要不变，原db20-r50 manifest、3份资源及39项来源无差异，无本轮临时写入文件遗留。文档检查不能替代Linux网络、进程归属、请求来源、真实费用或浏览器验证。

本批设计摘要：后端SHA256 df02919c6008b54cabcf96ba90b0b33e1a470e59560662ad057ecb07c4b235b3；前端SHA256 5d6b1907ab6192cf96ca280ea1c9c426afecf4e330ff1ca162e3c5bae941a63a。仅用于接续核对，不是运行产物准入。


## 2026-11-16 开源来源核查与环境模型许可设计

- 范围：继续设计，核对本地源码与公开开源源码；未SSH、安装运行时、启停服务、运行产品／浏览器测试、构建或调用模型／计数API，未提交／推送。HEAD仍a0f40592702cb702ed928849ac540479c22c224f；保留原工作区改动。
- 文档结果：后端0.7／DRAFT、前端0.6／DRAFT、架构1.19／REVIEW，索引同步；大纲1.18字节不变。新增后端3.9—3.10、4.15.1—4.15.2、4.17—4.18、6.8、7.12及对应前端对象／流程／页面／API；仍位于pending，未合入正式设计。
- 源码证据：经GitHub连接只读检查gVisor seccheck／remote README与remote.go；当前master异步发送、拥塞可丢事件，不提供逐次发送前允许／拒绝协议，排除该现成事件流作为唯一模型鉴权。不是对全部gVisor方案的否定，也未固定实际runsc产物。OpenCode对照现有1.19.5来源提交810c0eba1a7348036f8bdf61e6632d0c36c6876c，检查MCP／catalog、session/tools／prompt、工具注册、配置目录及插件／LSP／formatter执行路径；远程工具能力存在，但调用身份没有由显式MCP参数自动透传，不能因此认定原操作、取消和隔离兼容。
- 方案收敛：下一离线平台候选为固定OpenCode控制器与gVisor项目工具分开；必须先验证本地执行封闭、根连接来源、工具原操作和完整停止。未选定替代部署，未建设自制运行时／内核监控或fork。源码链接及Linux pidfd／proc依据在后端4.15.1—4.15.2集中列出，源码阅读不是实际连接证明。
- 许可规则：静态模型用途策略与动态许可分开，避免配置摘要循环；主体使用／签发／恢复审阅权限显式区分。许可和审阅保存在不随业务数据恢复的control_root，活动指针与hold同次更新；原任务／预算、LLMUse／费用预留和CountingJournal不复制。Guide Token预算不宣称金额封顶。恢复四项证据不全时不得确认，也无手工改账／强制绕过入口。
- 并发／失败审查：补齐撤销与发送提交点先后、安静边界才能替换、prepare与CAS断点、原键查询、旧主体失权、恢复审阅过期／高水位变化、控制仍CLOSED及跨代次ID碰撞；前端明确许可生效不等于任务已恢复。
- 文档静态检查：内存替换唯一性／输入SHA核对后，同目录临时文件flush／fsync、CAS复核及原子替换；临时文件已清理。Python只读检查6份Markdown的50个本地链接／锚点、八章职责、修订及验收编号、换行／围栏／尾空格；13项受保护输入、原db20-r50清单／3项资源及39项注册来源全部一致。此为文档／字节核对，不是产品验收。
- 新增TC201-AUTH-01—12、TC201-SRC-01—05及TC201-AFE-01—06，共23项待执行。许可文件Schema／适配器／页面、固定执行候选和故障注入均未实施，不能把条目写入当通过。

本单元检查时文档SHA256：后端10d3249a4536ff9fffccdf143f8e91e38c98c573c8a2a1910bb0e9ede9d21d34；前端6ef058be333710b2efa5eab7f5582136cbac2c579d853039b26923e6763ba9e3；架构59bb5d6e242ed06096328be96230827ba1095afd1431f79ae439bc6063569330；索引1d00c10e3ab832266dccd2e7a630ed365e682832f8b338428c838e0e079ab7b7。以上仅定位文档输入，不代替源码／运行产物摘要。

## 2026-11-16 Linux独立检查与本地Git交付设计

本轮接续设计及静态核对，未连接Mac／Linux、查询服务现场、安装运行时、执行产品测试／构建／浏览器或真实模型／计数请求；未修改产品代码、实际DDL／资源、业务数据或宿主配置，未提交／推送。保留原工作区改动，HEAD为a0f40592702cb702ed928849ac540479c22c224f。

阅读范围：V2.01索引、当前断点、前后端相关对象／流程／资源及架构11章；V2.0后端7.2、7.6、7.7、APP-TEST-RUN和交付契约。静态对照task_candidate_runtime／commit、task_verify_candidate、task_project_check_worker、testing/run_ownership／run_stop、check_driver_pipe_worker／SDK、owned_check_http、git_bundle／git_ref_protocol、task_delivery_write／write_runtime／window／finalize。长模块按关联函数／调用检索，不宣称重审全代码。另核对repository_acceptance、repository_baseline_input／validation／verify／snapshot_reads，db20-r50的code_snapshots与触发器，以及前端交付工作区、检查／报告／Snapshot解码及恢复入口。

| 本次发现与约束 | 最终设计处理 |
| --- | --- |
| Linux只打开文件／改chmod不等同Windows拒绝写句柄 | 捕获前关闭新写入并结束完整项目写入者；封存后不覆盖发布，检查只用只读产品副本；原生会话无法满足时保持能力不可用 |
| Coding自检、项目退出0与独立验收容易混用 | 复用原owner、计划／包、可信断言和资格；UI分别显示结果、适用性、停止及任务状态 |
| 现成浏览器镜像不证明沙箱和原通道安全 | 固定Linux SDK／浏览器闭包，非root及Chromium沙箱、独立driver、受控端点与可信结果通道；缺证据不能关闭隔离补过 |
| 原基线引用只含snapshot_id，恢复后ID复用可撞旧ref | GIT201-BASELINE-1增加原环境／原数据代次，Snapshot两字段不可变；历史引用不按新代次重算 |
| 基线先写Git后登记数据库，恢复可能跨代次补记 | 新插入约束对照不可变原REGISTER_BASE输入，不强制等于当前代次；已有可靠写入仅补原事实，旧操作缺失不新造同号记录 |
| Git与业务库不同事务，恢复旧库可能丢失较新写状态 | 原Git效果置于control_root恢复范围之外；可能已发、ABA、孤立效果均只核对，保留仓库占用 |
| 原仓库互斥只在同库repository_id生效 | 同实际common_dir长期归属单环境；别名／worktree不绕过，多环境独立仓库副本 |
| Git成功、postcheck与Task完成不同 | 保留原状态及单次引用事务，显式Linux对象／引用持久性设置待实证；界面只确认服务器本地分支，不宣称push或部署 |
| 旧报告可以查看，但不能认作当前运行 | HTTP绑定与历史证据原代次区分；原业务规则重核适用性，旧命令不跨代次继续 |

文档交付：后端0.8／DRAFT新增3.11—3.12、4.19—4.21、6.9、7.13—7.14及关联修订；前端0.7／DRAFT新增3.8、4.11、5.14、6.8；架构1.20／REVIEW与索引同步，大纲1.18保持原字节。新增TC201-CHECK-01—12、TC201-GIT-01—10、TC201-CDF-01—08，共30项待执行验收，未提前填写通过。

新Schema仅在文档中描述：预期73表／301对象，原297对象保持、code_snapshots表及其identity_fixed触发器两项修改，新增environment_binding表和原输入校验触发器。P1即使用最终结构；旧73表／300对象属于被替代设计预期，原运行证据仍只有旧72表／299对象。未执行新DDL、生成对象清单或改原db20-r50。实际构造器、严格解码、协议版本、原来源回执和反例均待A／P3实施。

外部依据核对Git update-ref与core.fsync语义、Linux cgroup v2停止／冻结、Docker只读挂载及Playwright Docker说明，原文链接在后端4.19—4.21节。关于如何满足本项目可信检查、完整停止和持久性的选择是方案约束；官方文档不证明固定组件组合已经通过，也未把当前最新版当实际锁定资源。

实际文档检查：同目录临时文件写入、flush／fsync、原内容复核后原子替换，成功及失败路径清理临时文件。git diff --check及内存Python检查6份Markdown、52处本地链接／锚点、八章结构／修订、全部验收系列连续唯一编号、换行／围栏／尾空格通过；13项受保护输入、原db20-r50 manifest／3项资源及39项注册来源无差异。该检查不执行SQL或产品代码，不能代替Linux文件／浏览器／Git／故障验证。

本单元文档SHA256：后端1db9aebfb32ca14dc56f4d597e4e51fe3c23bce936027a6c9c4582c083887d2f；前端87dedcc12daae15cec05e21e8e31bd1fe6a63a96d0efd41c183bb5634465600e；架构b9f7e813bc6e6dadb9703716556faf54efaaa9670be1ab5c8943797580d39ad3；索引fd388dd7dc3e2ad2e0e1442812d2f45dedb9a8c6737d37c23a65d4211332b3bf。摘要用于接续核对，不作运行准入。

## 2026-11-16 历史缺失与首期云部署设计

本单元仅文档、代码静态阅读及官方资料调研，HEAD为a0f40592702cb702ed928849ac540479c22c224f；没有运行产品、SQL、SSH、浏览器、模型或计数请求，没有修改服务、配置、密钥或采购资源。静态核对coding_model_ledger中断恢复、coding_model_read结算来源与costs用量条件；PROVIDER_BILL枚举不作为已具备供应方原账补证工具的证据。

交付为后端0.9／DRAFT、前端0.8／DRAFT、架构1.21／REVIEW及索引，大纲1.18原字节保持。后端4.22／6.6.2区分原调用集合缺失、最终费用未知、原写入未知及资产损坏；新增恢复中已核验资料的受控只读条件，不解除CLOSED／hold、不结束原RESTORE、不自动清空或重发。前端4.12／5.10／6.5同步范围、原因、原结果及备份时效，未知不显示0。可信补证适配器仍待实际交付，永久缺证时不承诺完整Agent恢复期限。

架构3.2—3.4以当日官方标准价核算：内地2核8GB／80GB参考月价95元，12个月85折计算首付969元、月均80.75元；加规划备份10元与独立验证余量25元为115.75元。不是用户账号结算价或已提高预算。补齐实际容量／磁盘／入口／Mac离线门槛、每日备份及7日点／4周点／2月点并集保留建议；数据RPO24小时、资料只读RTO4小时均为待演练目标，不等于AI恢复保障。价格、计费、COS域名要求与Restic配置的官方链接见架构正文；COS与Restic默认寻址方式存在差异，候选显式使用dns及实际region，尚无真实存储兼容证据。

新增TC201-REC-01—10与TC201-RCF-01—06，共16项待执行验收。文档静态检查覆盖6份Markdown、52处本地链接／锚点、八章结构及修订、验收连续唯一编号、LF／围栏／尾空格；13项受保护输入、原db20-r50清单／3项资源及39项注册来源无差异；git diff --check通过。检查不执行产品代码或DDL，不能证明恢复、云容量或供应方能力。

本单元文件按同目录临时写入、同步、原内容复核和原子替换保存，并清理临时文件。正文摘要：后端d216c1de40151c505ac1cbfabfefff5b8c92f5b3ae2ccf88ba7107f30719585e；前端57c7126d2a42415f4f98c0b41bc306d2b1eddc477c9d429c64f9c4e6bda88f25；索引6c2481b043c185622790f479c53a6f45b2c1438407dabff91cd8ce6bfc2ab03b。架构5ac3456f61df5daa026bed5d8fcc07d56f9b925ed184c3cc5702ce01f207e849。摘要仅用于接续，不是运行准入。

## 2026-11-16 固定工具适配与方舟补证可行性设计

本单元仅接续设计、源码静态核对及官方资料调研；HEAD为a0f40592702cb702ed928849ac540479c22c224f。未连接Mac／Linux、检查服务现场、安装或运行产品、执行SQL／构建／浏览器／模型／计数／供应方账号查询，未改变业务代码、资源、数据、密钥、服务或采购；未提交／推送。

本地阅读范围：opencode_managed_config、task_model_ingress、coding_model_gateway／ledger／sse、model_gateway与costs的相关完整函数及调用；既有CountingJournal职责沿前轮已读依据，本轮不宣称重审其全部源码。上游读取固定OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c的plugin/tool与Hooks、plugin/index、tool/registry、session/tools、config/paths及config/config相关段；session/prompt按file附件、subtask、shell／command入口定位，不宣称重审完整执行器。核对方舟官方GetInferenceRequestUsage、CreateRecordExportTask、GetRecordExportTask及CSV字段说明，链接及精确能力见后端4.15.3／4.22.4。

发现并处理的关键问题：

- 自定义工具运行时含callID，公开ToolContext没有该字段；形成固定版本运行时校验候选，不冒充稳定SDK已提供全部身份。插件加载失败可能继续启动，pure又禁外部插件；加入实际插件／工具就绪门槛和禁止回退。
- 原生file附件可能直调内置read，shell／command及subtask也有独立路径；工具隐藏与普通hook不构成完整隔离，控制入口与配置加载一起纳入SRC验收。
- Coding保存的HTTP头x-request-id、普通调用的body id及供应方查询的metadata RequestId不同；补证按独立来源身份关联，不改旧字段含义或猜测相等。
- 方舟有单请求查询及导出，但CSV计量数量不是金额，正常后付费覆盖也不能证明所有调用范围；原绑定、最终性、未决费用及外部写入仍分别核对。查询／导出次数、未知创建、截断及临时下载清理进入受限维护适配契约。

交付：后端0.10／DRAFT、前端0.9／DRAFT、架构1.22／REVIEW与索引；大纲1.18原字节保持。后端新增4.15.3、4.22.4，补充3.10／7.12及验收；前端沿原能力／四项审阅增加安全原因与展示，不新增账单控制台。架构11.3图按分离候选明确控制器和工具沙箱位置，11.4同步网络边界，11.6保留灾难恢复限制。新增SRC-06—09、REC-11—15、RCF-07—09共12项待执行，未实施适配器或提前填写通过。

实际检查：同目录临时写、同步、原内容复核及原子替换保存，临时文件已清理。内存Python检查6份Markdown、52处本地链接／锚点、前后端八章／当前修订、验收连续唯一编号、LF／围栏／尾空格均通过；13项受保护输入、原db20-r50 manifest／3项资源、39项注册来源无差异；git diff --check通过。没有执行产品代码或DDL，静态检查不替代平台来源、工具兼容或供应方真实证据。

当前文档SHA256：后端60bd5718f68eb6a2b2e9ef53f794a1111c6e8b057622180e853a580322121e54；前端da35d695140e77dd9a5f0d18ab81fce144cd637f0124d6bf83e44505efeb05a4；架构6ceb963092b3b7f3aeb020fe39242b87e2025bf5a4a7c8a60e84de8c38966e0e；索引647eff0d1f07e972d4e1ff11b0abb6203ce920a8e89148eb90b94422b69c9322。摘要只定位当前设计输入，不作运行准入。

## 2026-11-16 Linux逐段来源与固定执行包设计

本单元仅设计、源码静态核对与官方资料调研；HEAD为a0f40592702cb702ed928849ac540479c22c224f。未连接Mac／Linux、读取服务现场、安装运行时／策略、编写原型、运行产品／SQL／构建／浏览器／模型／计数或供应方账号查询，未修改业务代码、资源、数据、密钥、服务；未采购、提交或推送。

读取范围：当前V2.01索引／断点、后端4.13—4.15、6.7、7.11及关联来源契约，前端执行观察与验收、架构对应调用及网络；静态对照guard_task_model_source、TaskModelIngress完整来源／窗口路径、coding_model_listener接收／解析／排队／派发及task_initial_prompt配置核验、运行包隔离规则。上游核对固定OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c的provider自定义fetch、AuthHook、project装配与config相关段；Linux v6.8的net/unix/af_unix.c及net/core/scm.c只读相关凭据发送／接收函数，不宣称完整内核审查。Bun Unix fetch、Linux Unix／recvmsg／pidfd、Python3.13 socket及Ubuntu24.04 AppArmor官方说明见后端链接。

新增设计：后端0.11第4.15.4将优先候选固定为OpenCode进程内fetch→专用Unix socket→原模型网关。SO_PEERCRED只作连接交叉核对，SO_PASSCRED／recvmsg覆盖头、正文前缀与每段正文；缺凭据／截断／混合发送者拒绝，原pidfd、固定控制器策略和发送前重核配套。明确同PID exec仍需强制策略封闭，当前普通recv读取不能直接当逐段核验。仅静态查到API／源码，实际固定二进制内嵌Bun、内核／策略、插件与业务兼容未验证。

后端7.11.1定义新OC201-MODEL-UNIX-1候选与固定组件闭包、平台proof及接入顺序，复用原HTTP限界、窗口／许可／费用链路；旧plugin=[]及TCP配置校验不能直接删掉。OpenCode global项目可能将worktree置/，因此工具根只能来自原业务登记。前端0.10沿原reason_codes显示传输／来源／隔离未准入，架构1.23同步调用及网络，README收敛为导航；大纲1.18原字节保持。新增SRC-10—16与EFE-08共8项待执行验收。

实际静态检查：同目录临时写、fsync、原内容复核及原子替换，临时文件清理完成；内存Python检查6份Markdown、53处本地链接／锚点、八章／修订、验收连续唯一编号、LF／围栏／尾空格通过。13项受保护输入、原db20-r50 manifest／3项资源及39项注册来源无差异；git diff --check通过。检查不执行产品代码或DDL，不证明来源／隔离已通过。

文档SHA256：后端19fcd18f5bf4170de4d36f9f3b6f7a3ba3dae0a202bf51939aaef2955ca16e58；前端cc3c8f0ef78784377f07040a91efadf36cffcf961ac8ebb0df0598eb7a47fbbb；架构073de28d7d3c1ab2a41c44bb3a690a1d9939ddb32e43a0133c55a02019115be3；索引0df5dd4ba612d11dc3e9dcf5fadc04779e28159dcdea1b2e38062527aee646fe。仅用于接续定位，不作运行准入。

## 2026-11-16 控制器冷启动与工具结果兼容设计

任务仍为“继续推进设计”；本单元只读源码／官方固定来源及修改既有Markdown，不启动产品实施、SSH验证、安装策略、模型／计数或供应方查询。Git基线a0f40592702cb702ed928849ac540479c22c224f；既有五份文档改动保留，未改业务代码、资源、库或服务，未提交／推送。

实际核对范围：

- 本地opencode_runtime_bundle、windows_task_runtime_environment、opencode_instance_control、task_initial_prompt与task_native_policy：固定空插件／启动标志、严格文本消息及显式标题、原生权限编译和模型别名；结合既有任务窗口／角色／候选契约，不把Windows读取策略原样当Linux授权。
- 固定OpenCode1.19.5来源提交810c0eba1a7348036f8bdf61e6632d0c36c6876c：config及paths、project/bootstrap、core/npm与project／Git发现、tool/registry／truncate／question、agent装配、session/prompt标题／compaction／summary与snapshot、VCS、runtime-flags相关分支。通过GitHub只读读取，具体来源链接在后端4.15.5及7.11.2；未在工作区保存或执行上游源码，未核验实际平台二进制。

发现并修订：

1. 安装／bootstrap有错误被消化的路径；Npm.install跳过不证明依赖完整。改为安装时预置、受信成员核验、固定搜索目录与实际配置／适配就绪，保持模型窗口先关闭。
2. Git发现、原生snapshot、自动标题与压缩职责分开；保留可写会话状态、原问题／权限与业务角色交接。原生SessionSummary差异计算不是模型总结；禁用它的快照来源不能把真实候选变化清零。
3. 自定义工具返回仍会经过原生截断并生成控制器本地文件。新增有界结果封装、原任务引用及只读续页；大小初值与配额为待容量验证的设计值，限额／缺失不触发命令重做或释放未知效果。
4. 前端同步依赖／配置／结果诊断，复用原任务显示，不新增本地文件读取或自动修复开关。

保存为后端0.12／DRAFT、前端0.11／DRAFT、架构1.24／REVIEW；大纲仍1.18。新增TC201-SRC-17—20与TC201-EFE-09共5项待执行验收；SRC现20项、EFE现9项，不能记为通过。

静态核对：内存逐项diff及保存读回；使用python -X utf8 -仅标准库读取Markdown、AST与文件摘要，6份文档／53个本地链接及锚点、前后端八章／修订、验收编号、三项诊断映射、UTF-8／LF／围栏／空白均通过；git diff --check通过。13个受保护输入未变，原db20-r50的3个资源及39个登记来源无差异；同目录原子保存临时文件已清理。源码阅读没有替代类型、构建、浏览器、隔离或业务验收，这些本轮均未运行。

设计文档SHA256：后端14bb304529c0aa840ff34fe40adc0ffba18123aee5fc83487d0ef24cdd899270；前端f5fa797e6d15b978ccaca2cefc6a60f946d0946ba4b4cf6d84f1983b3ae6d8c3；架构f0d8b36dd3d9478d6b1c54730301c662bdf498fcd01c190d671de8b0efec933c；索引5ab10a87c5f746273df991bf70d6a3ba7d14bfff7ed0a9a2c4acfa53923edd92。仅定位本单元设计，不构成执行准入。

## 2026-11-16—17 工具授权与取消边界设计

本单元继续设计及源码静态核对，最终文档检查于2026-11-17完成；HEAD为a0f40592702cb702ed928849ac540479c22c224f。未连接Mac／Linux或查询服务现场，未执行产品、SQL、构建、浏览器、模型／计数或供应方请求；未修改业务代码、实际Schema／资源、数据库、密钥或服务，未采购、提交或推送。

实际阅读范围：本地execution_profile_content、authorization_scope、execution_profile_resources、managed_read_scopes及task_native_policy；native_permission_objects、task_native_issues、task_permission_response、task_issue_reads的授权／观察／决定／投递关联分支；命令准入、coding_check_plan、content_paths与task_project_check的相关调用；前端code-task-issues严格解码、permission-response-control及native-issues展示位置。对照V2.0后端APP-CODE-QUESTIONS完整规则和原db20-r50的code_commands／code_permissions字段及不可变约束，未执行或修改冻结SQL。长模块按完整关联函数与调用核对，不宣称全仓审查。

经GitHub连接只读核对固定OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c的session/tools、permission/index、plugin/tool、tool/registry及session/llm/request相关路径：插件execute不会自动检查具体业务对象；工具集合过滤、原ask决定及实际派发是不同环节；once释放原等待，reject影响同会话待批项，AbortSignal不能证明外部资源已经停止。来源链接集中后端4.15.6，未下载运行上游产品或将源码阅读当作固定二进制证据。

本单元修订：

- 六类固定工具复用原授权：读取、检索、写入、补丁、已登记命令与原结果续读；模型不提供身份、任意程序／参数／网络。文件前提与原内容摘要重新核对，跨文件不承诺整体事务。
- 项目命令只接受原EXECUTION命令ID，独立短时沙箱及原网络范围，全部资源计入原任务名额；CHECK／SERVICE仍走原检查计划。命令成功不直接产生独立检查通过或交付资格。
- OC201-TOOL-AUTH-1将原工具操作、输入、对象、授权及配置绑定；命令确认另绑定已核清写入高水位。复用原权限接口／记录，新增严格tool_binding及对象投影，不创建第二套批准中心或新的数据库表。
- 单次允许不扩大原范围；拒绝前稳定同会话待批集合，拒绝后逐项核对原回执；取消按派发前后分别处理，迟到回执不重新启动动作，未知效果不重试或提前释放占用。
- 前端沿现有权限卡片显示具体动作／对象、拒绝范围及确认／执行／停止的不同事实，补齐三项诊断与未知结果的恢复状态。

交付为后端0.13／DRAFT（4.15.6、6.7.1、7.11.3）、前端0.12／DRAFT（5.12.1、6.6）、架构1.25／REVIEW及索引；大纲1.18原字节保持。新增TC201-SRC-21—25及TC201-EFE-10—11，共7项待执行验收；SRC现25项、EFE现11项。适配器、页面、工具操作持久记录及运行验证尚未实施，不能将本单元标为功能完成。

实际检查：同目录临时写、flush／fsync、原内容摘要复核、原子替换及读回一致性核对；临时文件已清理。python -X utf8 -以内存脚本只读核对6份Markdown、53处本地链接／锚点、前后端八章／修订、所有验收系列连续唯一编号、六工具映射及前后端权限投影／诊断、UTF-8／LF／围栏／空白，failures为空；git diff --check通过。13个受保护输入、原db20-r50清单、3个资源及39个登记来源均无差异。未执行产品代码或DDL，不能替代Linux来源、工具兼容、隔离、取消和浏览器验收。

设计文档SHA256：后端8801b1a1bed4cfb980080a90754aecb4fe86c6ba481489113e069842446c04ff；前端4da6dc217b36d5b9ccb4e87f0442f60333a31b2dbf1858200038c98f6fc83330；架构f712534f496959d2ca384360f9d8c3911668e519f333d70d0e77782381fe42c9；索引fedb84642225eba669f4b1c3dd89ba6e37ab1b2cb1b36809cca7896c2a33381f。摘要仅定位本单元设计输入，不构成执行准入。

## 2026-11-17 工具恢复设计核对暂停

用户要求停止推进，仅做收尾。本轮尚未修改前后端设计、架构评审或索引；当前设计版本保持后端0.13／DRAFT、前端0.12／DRAFT、架构1.25／REVIEW及大纲1.18。没有新增已定案协议、接口或验收项。

本轮只读范围：原OperationRecord／CommandExecution契约、operation_protocol与task_operation_reads；task_records的原生观察及项目输出登记；task_model_ingress的ModelWindow归属；task_project_check的命令登记／完成；task_runtime_stop的写入核对及相关停止分支；task_candidate_git的命令预留／原范围持久化；project_check_journal与runtime_launch_journal的意图／回执机制。并核对task_role_reconciliation的受理／结果投影、task_read_api的动作资格、task_resume的等待条件，以及前端code-task-reconciliation、code-task-operations、role-reconciliation的相关解码和展示。长文件按关联函数阅读，未完成工具恢复方案的全链路审查。

已发现但尚未写成设计定案的缺口：

- 原OperationStep仅允许已登记业务步骤，不能直接追加每次工具调用；现有ExecutionRecord是观察文本，不能充当派发前的可信效果记录。
- code_commands已有EXECUTION用途，但本轮所读成熟路径主要用于CHECK和CONTROL_GIT；工具调用与命令记录的一一关联、跨存储中断及补记规则仍需明确。
- 原核对接口目前主要覆盖角色、修复及交付；原启动操作即使已成功，其后工具效果也可能未知。接口、等待事项、继续资格和前端结果提示需联合设计，不能仅扩大一个枚举。
- 文件原子替换与可信回执保存不在同一事务；回执丢失不能据文件内容相同、文件消失或进程退出直接推定历史成功。恢复核对与重新执行必须分开。

只读参考：[Linux fsync](https://man7.org/linux/man-pages/man2/fsync.2.html)、[Linux rename](https://man7.org/linux/man-pages/man2/rename.2.html)。前者说明文件同步不自动覆盖目录项持久性，后者说明原子替换及不覆盖发布语义；这些资料不证明本项目的Linux实现已完成。

停止时Git HEAD仍为a0f40592702cb702ed928849ac540479c22c224f，保留之前的五份文档改动。本轮仅将以上范围和断点写入本记录；未修改业务代码、资源、Schema、数据库、密钥或服务，未连接Mac／Linux、启动任务、执行产品测试／构建／浏览器／模型／计数请求，未采购、提交或推送。没有本轮新启动的进程、下载文件或测试产物需要清理；收尾仅核对记录保存、原四份设计摘要及临时写入文件。

## 2026-11-17 工具持久身份与中断恢复设计

用户重新要求继续推进设计，本单元接续上节暂停处；仅设计与静态核对，HEAD仍a0f40592702cb702ed928849ac540479c22c224f。沿用暂停前已经阅读的本地源码／Linux接口资料，对照当前原键、ModelWindow归属、固定业务步骤、命令／观察记录、核对／等待／继续及前端严格解码；没有把候选私有日志当作现有实现。本轮未SSH、查询服务现场、改业务代码／资源／DDL／数据库、运行产品／浏览器／构建／模型／计数，未采购、提交或推送。

本单元交付：

- 后端0.14／DRAFT新增3.8.1、4.23、6.7.2、7.11.4：工具是原任务控制证据的子记录，业务父操作及步骤不任意扩展；固定原键、原输入、意图、取消、效果、结果和命令关联，重启不改旧键以重复派发。
- 明确CommandExecution与安全观察的ID预留／持久关联／固定ID补记顺序，允许未使用序列间隙；数据库提交未知、效果后补记失败不创建第二次执行。原生观察文本不充当可信效果，未伪造原生事件。
- 补齐登记、权限等待、派发、文件／目录同步、命令创建／结束、返回丢失、跨代次恢复和控制记录损坏等中断处理；工具资源纳入原停止与自然收尾，不按当前session或零命令行判断全停。
- 原接口增加严格工具恢复观察及核对结果变体；父操作已SUCCEEDED不自动消除工具未知。RECONCILE只查证，保持原等待供明确RESUME重新核验并消费，避免先解除等待导致继续路径失配。
- 前端0.13／DRAFT新增5.12.2并扩展6.6：区分核对完成、效果核清、任务可继续和输出不可读；已成功父操作可从原详情查询，不只依赖active_operations。架构1.26／REVIEW及索引同步，大纲1.18保持原字节。

新增TC201-SRC-26—31及TC201-EFE-12—13，共8项待执行验收；SRC现31项、EFE现13项。每任务工具数／控制记录／输入及应急空间为固定包设计初值，仍需容量验证。文件提交回执缺失的可靠恢复判据、原生轮次已关闭后的可继续条件和固定平台故障证据尚未验证；不能宣布工具恢复或完整架构已验收。不增加实际数据库表，最终新结构仍为73表／301对象的设计预期。

实际文档检查：原内容SHA核对后，同目录临时文件写入、flush／fsync、原子替换及读回，临时文件清理完成。python -X utf8 -以内存脚本仅标准库读取Markdown、AST和摘要，6份文档、53处本地链接／锚点、前后端八章及修订、验收连续唯一编号／表格列数、恢复协议及前后端诊断映射、UTF-8／LF／围栏／尾空白检查通过；git diff --check通过。13个受保护输入、原db20-r50清单、3项资源与39个登记来源无差异。以上不执行产品代码或DDL，不代替Linux运行及故障验证。

设计文档SHA256：后端c05c95eeb33f9d24f1f72ec44f48cb5461a0a6294930cd70f4d502186d0b5c41；前端b7cb81e9c9261b5e955d8abeeeb33ee5597ad979ba131a74c71e43362393f565；架构4ce67ab3b02834a4da2ed450a31e4e3921b013aaea27d1208a7d80a7872f7181；索引d0f7a12afff5e3872710e5d3f0bb217b20217eef5f592c7ea821a9957ff0fc3c。仅用于接续定位，不作运行准入。

## 2026-11-17 文件效果证明与原会话接续设计

本单元按用户“继续推进设计”接续；HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。仅修改既有前后端迭代、架构评审、索引及本记录；未SSH或查询服务现场，未改产品源码／Schema／正式资源／数据／密钥，未运行产品测试、构建、浏览器、真实模型／计数或供应方补证，未采购、提交或推送。没有启动新的产品／测试进程或保留原始报告。

静态阅读包括task_resume／task_resume_runtime的来源窗口、等待、发送意图及完成事务，task_instance_driver的继续内容／投递／观察，opencode_instance_control的精确原消息与工具终态，task_session_replacement和相关repair前提；同时对照Windows私有记录、候选文件发布与旧文件归档观察的关联函数。长文件按完整相关函数读取，未宣称全仓审查。现代码主要接续HELD窗口，driver依赖活owner.gateway；仅数据库可读不足以恢复发送资格。原会话替换有固定候选、活实例及Windows专属证明，不是通用进程重建路径。

公开来源核对：[Linux rename](https://man7.org/linux/man-pages/man2/rename.2.html)、[link](https://man7.org/linux/man-pages/man2/link.2.html)、[fsync](https://man7.org/linux/man-pages/man2/fsync.2.html)，以及gVisor提交bf5df9a1c9211afe4dbd7267c4423e9ae575f7fa的sys_file、gofer/filesystem和runsc/gofer/fs/lisafs对应路径。官方仓库已重定向到gvisor/gvisor，按实际地址固定源码；gofer源码支持EXCHANGE／NOREPLACE分支，但shared互操作模式拒绝NOREPLACE。来源链接及采用限制见后端7.11.5；源码支持不等于固定运行二进制或ARM／云环境已准入，本轮未下载运行gVisor。

本单元交付：

- 后端0.15／DRAFT的4.23.1及7.11.5给出OC201-FILE-EFFECT-1有限候选：原对象／准备文件锚点、同文件系统提交、完整缺失目录分支、前后布局判据、同步及私有清理。派发意图与文件提交意图区分；混合布局／材料丢失不凭内容相同判成功。
- 恢复观察与原回执区分：RECOVERED_STATE只能证明本次核验的当前布局；原回执缺失仍保留MAY_HAVE_DISPATCHED及UNKNOWN outcome，不重放原工具、不伪造原生成功。清理／全部写入者核清后才释放，观察本身不重新开放模型。
- 4.23.2明确HELD、同实例CLOSED、仅后端重启、执行器退出／宿主重启的不同条件。修正6.7.2提前消费等待的风险：受理新RESUME时保持原等待OPEN，确认精确新消息接收并完成原事务后才解除；未知投递只查原新消息。
- 前端0.14／DRAFT的5.12.2／6.6同步四项安全诊断、当前效果与历史回执、继续请求受理与真正继续的区别；不承诺所有任务都可修复／自动接续，不从202本地清除等待。
- 架构1.27／REVIEW及索引同步；大纲1.18原字节保持。新增TC201-SRC-32—36和TC201-EFE-14—15，共7项待执行验收；SRC现36项、EFE现15项。有限文件协议、Linux原控制接管及CLOSED来源分支均尚未实施或验证。

实际文档检查：同目录临时写入、flush／fsync、原SHA复核、原子替换及读回通过，临时文件已清理。python -X utf8 -以内存标准库脚本静态核对6份Markdown、53处本地链接／锚点、八章结构／版本、全部验收编号及列数、文件／继续协议、四项前后端诊断与等待时点、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。13个受保护输入、原db20-r50清单、3项资源及39个登记来源无差异。这些检查未执行产品代码或DDL，不能替代文件故障、模型接续、隔离及浏览器验收。

设计文档SHA256：后端25c82996501444c0427e9a43c8fa850a2fdcc813c54449190ae584c2e5661837；前端db805615b2127bf93a1f7da55640440d4c286bd2d040823f6a959a81db545b8b；架构7cb5705abe16afe050e7991d2fa14b8ed06cfeb2a1ad8604b6dd37444b1a3ff1；索引2ad1035dd0f0d4a67ecb109a717140f510e61d03e66f18161fe1d5f0451b2eb9。仅用于定位本单元设计，不构成执行准入。

## 2026-11-17 后端重启后的有限控制接管设计

本单元接续用户“继续推进设计”，HEAD保持a0f40592702cb702ed928849ac540479c22c224f。仅设计、相关源码和公开原始资料核对；没有连接Mac／Linux、查询服务现场、修改产品源码／Schema／正式资源／数据／密钥，没有运行产品测试、构建、浏览器、模型／计数或供应方补证，也未采购、提交或推送。本轮没有新产品进程、下载产物或原始报告需保留。

已读范围：task_instance_driver的_Owner、启动装配、继续／观察及停止归属；task_runtime_recovery完整原范围恢复与允许动作；guard_controller_binding及guard_controller_owner的真实进程／任期与重连；task_model_ingress的ModelWindow严格关联和准入；coding_model_listener的TaskModelRoute及队列／撤销；task_resume_runtime发送意图及完成事务；task_runtime_files的凭据签发／绑定、opencode_control的原凭据／通道及opencode_model_credential派生。长模块按完整关联函数核对，未宣称全部源码已审阅。现RuntimeTaskRecovery只接受OBSERVE／STOP／RELEASE，原_owner、网关和凭据依赖活内存；这些约束不能靠读SQLite解除。

公开原始依据：[Linux v6.8 SO_PEERPIDFD实现](https://github.com/torvalds/linux/blob/v6.8/net/core/sock.c#L1671)、[pidfd退出观察](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)、[Unix凭据／SCM_RIGHTS](https://man7.org/linux/man-pages/man7/unix.7.html)、[pidfd_getfd权限及区别](https://man7.org/linux/man-pages/man2/pidfd_getfd.2.html)。只核对机制：真实peer进程引用、打开对象引用传递和进程退出，不将数值PID／FD、文件锁内容或源码支持当成实际平台准入。没有测试内核选项或调整权限。

交付为后端0.16／DRAFT、前端0.15／DRAFT、架构1.28／REVIEW及索引，大纲1.18原字节不变：

- 3.8.2区分业务后端、宿主执行控制和OpenCode三类身份；原启动／工具证据保持原值，新attachment单独关联当前后端，业务control_generation不因接管自动变化。
- 4.23.3限定仅后端重启、原执行控制进程连续存活且原能力未丢失的接管；先封闭旧资格，再持久绑定、交付活能力、补记原等待。连接超时不授予抢占，接管不自动发模型／旧消息或解除等待。
- 7.11.6给出OC201-CONTROL-ATTACH-1、原请求去重／CAS、活pidfd与临时凭据交付、控制帧边界、监听重建及中断矩阵。模型接口仍拒绝FD传递；不增加第二套业务库、常驻模型代理、通用秘密恢复服务或分布式选主。
- 原接管只支持稳定业务来源；旧START／RESUME／角色／修复／权限投递未完时仅核对、保全及原终止。尤其原新消息已收到但旧RESUME未完成，不能让新后端调用旧完成分支开放模型；原费用／效果事实仍保留。
- 前端沿原任务观察显示“重新连接”与“可以继续”的区别，映射三项新增诊断；无任意接管、强制抢占或重发按钮。架构明确首期模型网关留在业务后端，执行控制独立持有原资源，未声明该部署已实现。

新增TC201-SRC-37—42及TC201-EFE-16—17，共8项待执行验收；SRC现42项、EFE现17项。真实单实例资格、活能力／通道／权限组合、固定控制丢失策略及故障矩阵均待平台实证；本次定义范围不等于Agent能够自动恢复所有工作。

实际静态检查：同目录临时写、flush／fsync、原摘要复核、原子替换和读回一致，临时文件已清理。python -X utf8 -以内存标准库脚本检查6份文档、53处本地链接／锚点、八章与修订、验收编号／表列、文件与接管协议／前后端诊断、跨任期消息及FD边界、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。13个受保护输入、原db20-r50清单、3项资源和39个来源保持不变。以上未执行产品代码或DDL，不替代Linux运行／隔离／恢复验收。

设计文档SHA256：后端fc19fa2562f85345e5be82f828c2812d293f61a5e8bcb8f7ad9cbd7c4010605e；前端95a0dc147cfbbd76745ad2de11e79b183b9d55b743e13e50144840c8e5934a2f；架构a334465bce35e0ec2e10078dd88163bfe65296cdae65021115b62e18acef3766；索引0c2067fa1e3f6b7587b0fd9ae74748cb2c12b3d9e56e963b2db58a80013aef80。仅用于定位本单元，不构成执行准入。

## 2026-11-17 稳定锁归属与控制通道准入设计

本单元接续用户“继续推进设计”，HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。仅修改现有待合入Markdown和本记录；未实施产品代码／Schema／资源，未连接Mac、查询服务、执行产品测试／构建／浏览器或发出模型／计数／供应方调用，未采购、提交或推送。无新产品进程和测试产物。

已读process_lock.py与execution_lease.py完整实现、guard_backend_program.py的固定程序包准入与实际身份核验入口（前约280行），以及现行设计3.2、3.6、7.2、6.7、7.11.6和架构6.3。现Linux分支使用flock、按库路径派生锁、assert_owned仅核对本地对象／PID／epoch，并将各类OSError混为已运行；这些是待适配缺口，不是本轮已修复代码。租约退休仍只解决进程内事务同步。

本轮查证[记录锁](https://man7.org/linux/man-pages/man2/fcntl_locking.2.html)、[flock](https://man7.org/linux/man-pages/man2/flock.2.html)、[unlink权限](https://man7.org/linux/man-pages/man2/unlink.2.html)、[Unix套接字](https://man7.org/linux/man-pages/man7/unix.7.html)及[recvmsg](https://man7.org/linux/man-pages/man2/recvmsg.2.html)。据此修正：文件本身属root不能阻止有权写父目录的进程替换路径；F_GETLK不能证明flock持有者；进程记录锁可查询归属但存在同进程任意close释放风险。程序／策略及各PID视图仍须联合核验，官方语义不等于现场通过。

交付为后端0.17／DRAFT、前端0.16／DRAFT、架构1.29／REVIEW及索引，大纲1.18字节不变：

- lock_root由安装方保护，与可变control_root分开；同一环境换库仍竞争原锁，普通启动不补建缺失锁，不保留旧路径兼容查找。
- OC201-ENV-LOCK-1固定整文件进程记录锁、独立持有者查询、唯一fd、错误分类、退出／租约退休顺序及失效任期。锁不是强制权限系统；额外close与混用协议必须先被实现约束和故障验证排除。
- OC201-CONTROL-FRAME-1固定受保护SEQPACKET、64KiB单报文、逐报文凭据／peer与原范围联合核对，异常FD清理及单一ATTACH能力交付。模型通道保持独立；不增加自研锁服务、通用RPC或调试权限。
- L0—L4矩阵区分现场清单、锁原语、报文夹具、失效恢复和实际包／部署联合准入；宿主夹具成功不能代替Compose中的双向身份和真实程序证据。后者仍是下一设计门槛，没有隐藏为已完成事项。
- 前端沿原启动／任务观察区分环境占用、归属未核实及资格失效；不提供清锁、强制解锁或自动重启操作。

新增PKG-09—10、SRC-43—48与EFE-18，共9项待执行验收；PKG现10项、SRC现48项、EFE现18项。没有执行任何新增Linux矩阵，也没有改变之前的运行证据。

实际静态核对：同目录临时写、flush／fsync、原摘要复核、原子替换并读回一致，临时文件清理；python -X utf8 -标准库内存脚本检查6份文档、53处本地链接／锚点、八章及修订、验收连续性、锁路径／协议／诊断和跨通道边界、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。13个受保护输入、db20-r50原清单、3项资源和39个来源无变化。仅文档静态检查，不执行产品代码或DDL，不替代Linux功能及隔离验收。

设计文档SHA256：后端75614b494c595409e9c30a517595569609b95cd04e717d5a74c7586df1513cca；前端641bba9e5376b7d7176ac4086a603a18c59192452e74911d69cb1c2dbb441683；架构59954a5ad6699149212e583ec93a0a403797ecd809a02b07e0cf06646567e227；索引db24f237c1f2c43f251f950c99c0c6e15258d3fe4f3921a0e55c69fc07a56dcf。仅用于本单元定位，不构成包准入。

## 2026-11-17 宿主服务部署与原生控制门槛设计

本单元接续“继续推进设计”，HEAD保持a0f40592702cb702ed928849ac540479c22c224f。仅编辑现有待合入设计及本记录，未改产品代码／Schema／资源／业务数据，未连接Mac、查询服务、安装systemd策略或启动任何产品／测试进程；未执行产品测试／构建／浏览器、模型／计数／供应方调用，未采购、提交或推送。无新增运行产物需清理。

基线为后端0.17／前端0.16／架构1.29，五份文件与上一单元最终摘要一致，工作区改动保留。已读guard_controller_binding完整内容，guard_backend_program前280行的实际peer／固定包及权限核验，task_instance_driver前340行的安装定义／Owner／启动装配，opencode_control前250行的原凭据、连接前对端检查、HTTP及SSE读取；未把上述长模块全部标为已读。原代码仍依赖Windows身份与原端点核验，不能只去掉类型检查换成Linux socket。

公开原始依据：

- [PID命名空间](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html)及[Docker Compose服务选项](https://docs.docker.com/reference/compose-file/services/)：核对跨层可见性和PID模式；未把host PID当默认补丁。
- systemd固定v255的[执行环境](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml)、[服务](https://github.com/systemd/systemd/blob/v255/man/systemd.service.xml)、[停止](https://github.com/systemd/systemd/blob/v255/man/systemd.kill.xml)、[只读管理接口](https://github.com/systemd/systemd/blob/v255/man/org.freedesktop.systemd1.xml)及[GetUnitByPIDFD实现](https://github.com/systemd/systemd/blob/v255/src/core/dbus-manager.c)。源码返回unit／InvocationID前重核pidref；程序闭包和业务权限仍需项目联合证明，未验证实际安装版本。
- [AppArmor策略](https://manpages.ubuntu.com/manpages/noble/man5/apparmor.d.5.html)及[Linux v6.8连接标签实现](https://github.com/torvalds/linux/blob/v6.8/security/apparmor/lsm.c)：核对强制模式、执行转换和标签边界；profile声明、标签或PID单项不是完整证明。
- OpenCode固定810c0eba1a7348036f8bdf61e6632d0c36c6876c的[server.ts](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/server/server.ts)完整读取、[plugin/index.ts](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/plugin/index.ts)client与加载路径：实际listen使用TCP，插件仅无serverUrl时才使用进程内fetch。未运行固定二进制验证原生控制兼容。

交付为后端0.18／DRAFT、前端0.17／DRAFT、架构1.30／REVIEW及索引，大纲1.18不变。后端7.11.8新增OC201-HOST-SERVICE-1，架构11.2.1同步真实运行位置：业务、执行控制和固定OpenCode为独立宿主服务；任务项目保持gVisor沙箱。此为设计选择，替代原“应用默认Compose”建议，不是已部署或已由用户逐项定版。Mac仍仅提供Linux开发／验证宿主，云生产不依赖Mac在线。

明确受信unit模板／只读pidfd查询、当前主进程与原调用代次、有效配置／固定程序闭包和实际LSM联合核验；分开业务、控制、Agent资源组，首批不自动重启原运行，超时不强制抹除未知。可变开发源码与完整候选资格分开，身份／挂载的特权准备仍是原受限适配的待实现资源，不把任意systemd管理权限交给业务。

发现并保留关键未决：原生OpenCode HTTP／SSE控制入口的Linux连接方法尚未定案。私有loopback不能从宿主直接当同一个localhost访问；原模型Unix通道不解决这个问题。禁止未证对端就发送Basic凭据、开普通宿主端口或用无身份保证的通用代理；若最小适配无法满足则按原候选退出条件重新评审。前端分别显示部署与控制通道未核实，普通页面可用不显示为完整Agent就绪。

新增TC201-SRC-49—54及TC201-EFE-19，共7项待执行验收；SRC现54项、EFE现19项，未执行Linux实际矩阵。其他P1、管理／维护／许可、费用恢复及检查／Git边界保持。

实际静态核对：同目录临时写、flush／fsync、原摘要复核、原子替换及读回一致，临时文件清理。python -X utf8 -标准库内存脚本检查6份文档、53处本地链接／锚点、八章／修订、验收编号、宿主服务／身份／诊断及原生通道门槛、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。13个受保护输入、原db20-r50清单、3项资源及39个来源不变；以上均不是产品或Linux运行验收。

设计文档SHA256：后端015f6ae5776e42ad72dd80a0d75e95b0d3f0d3d468c03fd878ef5fdd450a48bd；前端84ef5033e30293ea1f02a519255d80b0001159b901af1c8612ebc139d4691f35；架构823000db99c5004eaedc886b9648920ee6346f21ae28ba0550629621ce1706b6；索引b3bb2f4a1597d08158797209708fce6902f4b2755d449f57751c027404b48db8。用于定位本单元，不是程序包准入。

## 原生控制连接与断线核对设计（2026-11-20）

范围：用户继续推进设计；本轮只阅读本地相关源码、固定上游源码／官方说明和修订现有文档。HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。未运行产品测试／构建、SSH或浏览器，未查询或修改服务现场；无模型／计数／供应方补证调用、云采购、Git提交或推送。

本地核对opencode_control、opencode_instance_control、opencode_events、windows_task_endpoints的真实连接、固定方法、严格文本输入及限额；固定OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c的serve.ts确认instance=false，实例按请求目录装配。对照systemd v255的PrivateNetwork／JoinsNamespaceOf、Linux socket诊断及proc fd说明，区分网络可达、内核socket信息和原根所有权。现成systemd-socket-proxyd能转送字节，但不能传递原Unix peer凭据／pidfd，不作为本方案的认证依据。GitHub连接工具返回403后使用公开网页核对；后续网页读取也受403限制，未把未取到的Linux具体实现／新策略片段列为已审读。已取资料只支持机制候选，实际目标包／权限仍未验证。

交付：后端0.19／DRAFT、前端0.18／DRAFT、架构1.31／REVIEW及索引；大纲1.18不变。后端7.11.9的OC201-NATIVE-CONTROL-1复用既有固定原生方法，原control按每实例一份与OpenCode共享私有网络，业务通过受保护Unix操作入口连接。为避免全局调试能力，同实例共用专属UID并分强制profile／挂载，限定control单向proc读取；更新3.8.2／6.7／7.11.6—7.11.8及架构相应边界，不再保留control跨环境共用或所有角色必定各分UID的矛盾要求。

原生连接先证明实际已accept对端及原根fd，再发送凭据；固定配置读取负责触发初始化，不依赖插件先提供入口。输入有界分帧，原副作用派发先留意图，丢回执／SSE中断／接管只核对原记录；原Basic留在control，模型仍由原OpenCode直接进入业务网关。前端保留未知、原输入／幂等键及原结果，不把重新连接当已继续或已停止。新增TC201-SRC-55—60及TC201-EFE-20，共7项待执行验收；同UID反向拒绝、accept前零凭据及原生中断组合是新增关键门槛，尚无实际通过证据。

实际检查：同目录临时文件准备完整字节、flush／fsync、原摘要复核、原子替换、读回一致及临时文件清理。一次后续保存因工具返回元数据解析不完整而被摘要前置校验拒绝；核对实际文件未变化、修正元数据解析后完成，没有直接覆盖或丢失内容。使用node_repl中的Node标准库内存脚本核对6份Markdown、53处本地链接／锚点、前后端八章／修订、全部验收编号、原生协议／权限／旧结论一致性、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。9项受保护输入摘要不变，原db20-r50清单及其3项资源／39个来源全部匹配。以上是静态核对，不是Linux功能、隔离或产品验收。

本单元文档SHA256：索引aa8bffa85e13c3b28da19b41349632c0cbf7f1dd2f0d2f8e67a756d4902f9672；后端88e705860bec9f4ec5d4ad0a97d7d4c0a5e3f9bb345def365c7f6a8c4ea8a13b；前端c6088323e3258e7530d56640eda49577437d4792286c83011363a211d42fc753；架构dbcea4c8e939ad14adef81c37a885989e6bc80e6050f775024f345e58dd75ff8。实际来源／部署／故障原型仍未执行，下一步见当前断点。

## 安装权限、启动阶段及秘密交付设计（2026-11-20）

范围仍为用户“继续推进设计”。基线为后端0.19／前端0.18／架构1.31，工作区原改动保留，HEAD为a0f40592702cb702ed928849ac540479c22c224f。本单元只修改现有pending设计、索引及本记录；未改产品源码、Schema、资源或业务数据，未连接Mac、查询／变更服务、执行产品测试／构建／浏览器或发出模型／计数／供应方请求，未采购、提交或推送。

已读AGENTS及本版接续断点、后端4.13／6.7／7.11.8—7.11.9／8.3及关联前端／架构条款；本地核对opencode_task_launch、windows_task_runtime_environment、opencode_control及opencode_model_credential的启动／凭据构造，windows_task_native_launch的私有环境与原启动路径，task_instance_driver的启动装配及秘密检查调用、coding_model_gateway._check_credentials。长模块仅按这些范围核对，不宣称全模块已审读。现代码仍为Windows实现，Linux秘密拆分和原生结果检查迁移均未实施。

公开依据核对Ubuntu AppArmor策略的双向read／readby及执行模式，Linux proc／ptrace的真实凭据／dumpable／LSM条件，固定v6.8的AppArmor执行转换、fs/exec.c、kernel/cred.c和fs/coredump.c相关路径；以及systemd v255的执行环境／LoadCredential，固定OpenCode提交810c0eba1a7348036f8bdf61e6632d0c36c6876c的core/flag/flag.ts认证环境字段。链接放在后端7.11.10相应条款，未下载或保留源码副本。部分网页／GitHub请求返回403，取得内容的固定文件才作为依据；未以取不到的策略示例证明目标编译已成功。

本次解决的设计缺口：

- 同UID不等于能读原进程fd；明确UID／GID、能力、dumpable、双向LSM及proc挂载的联合条件。安全执行、NNP与dumpable分别核验，不把Px名称误写成exec后必定不可dump。
- NoNewPrivileges下不依赖任意profile互换；选用保留bootstrap约束的叠加转换，exec后再次核验完整标签与原活引用。固定启动器有界领取秘密，运行Agent失去该入口、总线及再exec权限；所有辅助FD关闭。
- Basic与内部模型能力使用独立秘密材料，移除Linux装配对Windows“同一口令种子”的隐含依赖；固定原范围握手只交付一次，丢回执／停止／exec失败均不补发、改密或另起实例。
- 原请求与结果泄密检查随Basic持有者移到control，并保留业务模型检查；完整解码后先检查再保存／分帧，拒绝输出不改写原效果。
- 核对core管道不按普通LimitCORE大小限制处理，补齐专用Linux VM的core／swap及日志准入；不为proc观察关闭所有保护，也不修改用户当前宿主设置。4.13同步澄清项目沙箱create与OpenCode宿主unit是两类资源。

交付为后端0.20／DRAFT、前端0.19／DRAFT、架构1.32／REVIEW及索引；大纲1.18不变。新增TC201-SRC-61—66及TC201-EFE-21，共7项待执行验收。OC201-STARTUP-1是安装与装配契约，不是新增产品状态或常驻凭据服务；没有交付可安装unit、LSM策略或启动器，固定平台能否满足仍须实际门槛证明。

实际静态检查：使用Node标准库内存脚本核对6份Markdown、53处本地链接／锚点、前后端八章及修订、全部验收编号／表列、启动权限／秘密／诊断一致性、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。13项受保护输入摘要不变，原db20-r50清单及其3项资源／39个来源全部匹配。同目录临时写、flush／fsync、原摘要重核、原子替换及读回一致，临时文件已清理。以上仅为文档与字节静态检查，新增7项运行验收均未执行。

本单元文档SHA256：索引1ef5cd1bdb8d4e3d9466803fa9343a02ea2c0b90bd07a8c675736c89c1d5bacb；后端075ce402639665d975241193d751092ff7bb82de88a130376c818c7942ea27ac；前端3598f2555b6176a106762541cdd494446e2b445168213c423af7e1280b12361a；架构fd49e11d4ce288c234d15708683bb0435c5ce647c6bb143f3f599573848ebf9e。这些摘要用于定位当前设计，不构成安装或运行准入。

## 普通业务装配与分批交付依赖设计（2026-11-20）

用户继续要求推进设计；本轮从后端0.20／前端0.19／架构1.32及当前断点接续，五份文件摘要与上节一致。Git工作区原改动保留，HEAD仍为a0f40592702cb702ed928849ac540479c22c224f。仅阅读本地文档／相关源码并更新现有Markdown；未修改业务源码、资源、Schema、配置或数据，未连接Mac／查询服务、安装依赖、执行产品测试／构建／浏览器、发模型／计数／供应方请求，未采购、提交或推送。

已读AGENTS、文档规则、本版3.1—3.3／3.6、4.1—4.5、6.4、7.1／7.3—7.5／7.7—7.10、8.1—8.3及前端8章／架构9、11.7关联规则，参考V2.0进度与映射的当前基线。源码核对__main__.py全部、service.py的工厂／生命周期／路由／准入（前260行）、local_deployment.py全部、repository_registration_worker前140行的类型／导入、GuideWorker构造／启动／监测／after_commit、production_options函数、HttpRuntime与提交后派发、schema_v20_assembly的fresh构造／静态命令常量、schema_v20_state初始化及来源校验、recover_workspace_starts／recover_drafts。没有执行这些产品模块，不将静态导入关系当作Linux已发生的运行故障。

发现并落实：

- 现普通入口仍经过Windows部署类型，service默认装配模型计数依赖和后台循环；不能只禁用按钮就声称普通业务已脱离执行平台。新增7.3.1定义真实组合入口、纯路由／数据规则与原生构造分离，保留同一GuideWorker／幂等／恢复，禁止用测试工厂或空worker代替实现。
- production_options当前仅构造TokenizationGateway，明确不在构造时读凭据／联网；纠正原4.2中可能误导的表述。普通模式仍要求不调用该工厂，但不编造已经付费的事实。
- GuideWorker.start早于service后续恢复开放accepting，且部分资源取得在生命周期清理try之前；设计要求统一最终开放和逐项登记清理，补足启动失败窗口。LOCAL_TOOL与应用交接不能持同一锁互等，未知START不能另起进程。
- A细分固定运行包、最终Schema和首环境准备，B负责真实普通装配，C完成两套scope的真实页面；P2-a机制夹具可独立推进，P2-b才接固定组合。管理与完整Agent未交付不阻塞已独立通过的普通业务；共享前提失败仍阻断，完整环境不自动降级。
- 同DDL／objects字节的来源更新不重建库或换代，保留原fresh checksum、绑定、草稿和请求；结构变化不得修改标记凑通过。平台包、开发源码、Schema来源及执行策略按真实影响重新准入。

交付为后端0.21／DRAFT、前端0.20／DRAFT、架构1.33／REVIEW及索引，大纲1.18字节保持。新增TC201-P1-11—12、TC201-FE-13，共3项待执行验收；SRC／EFE原数量和未执行状态不变。不新增设计文件、运行时协议或第二套实施记录；本轮没有开始A／B／C实施。

实际静态检查：Node标准库内存脚本核对6份Markdown、54处本地链接／锚点、前后端八章／修订、全部验收编号／表列、P1装配与分批引用、UTF-8／LF／围栏／尾空白，failures为空；git diff --check通过。16项受保护输入摘要未变，原db20-r50清单及3项资源／39项来源全部匹配。同目录临时写、flush／fsync、原摘要复核、原子替换与读回一致，临时文件已清理。以上只证明文档及保护字节一致，新增3项产品验收均未执行。

本单元文档SHA256：索引26e43a430a3096f7f8c9092b880edfd840f13aa46f3775c15380d9afcc97817e；后端c1a599621b672465c8591f520be082af9970b85d8ac3c5d44abd130a8e7675c7；前端ea7f62513a8f6110e056d4eddf5db1d1c58e7f4b48bcc22848b0947b11d952d1；架构d80e43f64c1f717f280dded128618a31ccee565e03f8cfe735dcc9255655db97。用于定位当前设计，不代表实施或运行准入。

## 设计收口（2026-11-20）

用户在询问设计进度后明确要求“那就收口吧”。本轮结束持续扩写设计，只核对现有文档的一致性与首批实际调用边界，修正具体遗漏，并保存实施入口；不启动产品实施、原型、云采购或正式规格合并。HEAD为a0f40592702cb702ed928849ac540479c22c224f，保留原工作区改动。

已读本轮项目约定与文档管理规则、业务大纲全文、详细设计范围／4.3—4.5／6.2／8章及架构方向／11.7—11.8，回查原分批与准入规则。源码核对requirements／documents／messages实际API与需求命令、文档创建／完成编辑／元数据处理、comments查询、GuideWorker.after_commit、shared/http_boundary以及card_commands.submit的模型／程序分支；前端核对RequirementDetailRead中CURRENT与评论索引的联合读取及panel-read恢复。其他源码只做定向检索或保护摘要，未声称整库重新审计，未执行产品模块。

收口修订：

- 大纲原来仍写选型未收口、详细设计待展开，与现有前后端不一致；同步为大纲1.19、架构1.34、前后端各1.0，统一BASELINED含义为“独立设计收口，附实施准入条件”。继续留在pending，不覆盖V1.5／V2.0正式或既有草稿。
- 后端4.3补上真实页面必须读取的评论索引，避免正文可读但详情组合失败；消息／评论只读不自动开放写入。
- 后端4.4.1明确普通人工命令、未接入人工分支、卡片答案、原结果和取消／有副作用查询的范围。卡片答案可能创建GuideRun；read_http实际复用handle_http并经过after_commit，不能只拦AI文本入口或在投影响应后拦截。能力在意图受理前与实际派发边界检查，旧成功回执不自动再派发。
- 前端对应真实读取、暂不可用原因和卡片提交限制；细化已有P1-04／06、FE-13反例，不新增测试编号、运行时协议或产品设置页。
- 两份8.3和架构11.8改为明确的收口／准入清单，删除累计推进式尾段。区分已定契约、待生成资源、待验证候选与首期不包含项：普通A／B／C可独立实施，P2先原语后固定组合；不兼容结构转换按具体源→目标另行设计，云实际接入是独立部署阶段。
- 本轮未重新查报价；旧价格保留原日期，只作候选依据。云预算、容量、供应方补证、Restic／COS恢复及完整执行证据仍未落实，不把设计收口变成生产许可。

实际静态核对：Node标准库内存脚本核对6份Markdown、59处本地链接／锚点、前后端八章结构、收口状态／修订及全部验收编号／表列，UTF-8／LF／围栏／尾空白与临时文件检查通过；git diff --check通过。33项规则、正式资料及相关源码／锁文件摘要未变，旧db20-r50的3项资源／39项注册来源全部匹配。6份文档均采用同目录临时文件、flush／fsync、原摘要复核、原子替换和读回核对；临时文件已清理。P1仍12项、FE仍13项、SRC仍66项、EFE仍21项，细化的产品验收均未执行。本轮没有新的Linux、浏览器、模型／计数或云证据。

收口基线SHA256（验证记录自身不作自引用摘要）：

| 文件／修订 | SHA256 |
| --- | --- |
| 索引 | bc4af5efc41989bc0d6ceeb4225a997bb311f5b581116f2a9ad58d0a46420e49 |
| 后端1.0 | a3e435cb541d59cd66defeccbc619a3f85414e53bace4ff400ea1deb8c72b96d |
| 前端1.0 | 0a5c079e0b6c2c0bb2d4e6ef4a7511c1a5cdf161e8bcffc70e00d48d0a4384e0 |
| 架构1.34 | 3a878cb9cc6cda1c0b0ea8704c7cc95025cbe13a2957801491982ba542389cb6 |
| 大纲1.19 | 88426de112400fa8e8e23669414eb3fd741ef2ca06a256eee71a53fa326250ed |


## 当前断点及下一步

任务状态：2026-11-20设计收口完成后停止本轮设计推进，等待后续实施任务；不是软件版本验收完成。最新基线为大纲1.19、架构1.34、后端1.0、前端1.0，均BASELINED／独立待合入。索引只作导航，收口门槛以后端8.3及架构11.8为准。

- **本轮交付与授权**：仅更新上述四份设计、README和本验证记录。没有未完成的产品函数或半成品代码；未改源码、锁文件、Schema、资源、业务数据、凭据或服务，未提交／推送。当前已读范围及静态结果见上节；实施时须完整阅读目标单元契约，不能把本次定向核对当作全项目实现检查。
- **实际证据边界**：基础SSH／文件／Windows浏览器连接、OpenCode离线原型、国内入口基础连通、固定Python3.13.18／SQLite3.54.1、31项依赖及前端构建／文件保护是前文记录的历史结果；最终新Schema、正常产品入口、双环境页面、执行来源／恢复、管理发布与云验收未完成。预期73表／301对象仍须实际构建核对。
- **开发与内部Agent**：Windows外部工具通过SSH操作Mac内Ubuntu ARM64；产品Agent用OpenCode及国内方舟／DeepSeek渠道。Linux原生Codex登录的地区限制403及登录进程清理是历史事实，不再作为产品开发前提，不复制Windows凭据或为此重装网络。
- **当前现场**：本轮未连接Mac、未核对服务或新建进程，不能保证历史地址／Running状态仍有效。上次清理后测试依赖副本已删除，/home/ubuntu/projects/walle-connection-check为空，完整产品工作区尚未建立；固定工具路径／摘要及VM状态以此前记录为历史依据。没有本轮待停止进程或待删测试产物。
- **实施启动入口**：先读AGENTS、本版本README、后端1.0的7.3.1／8.2／8.3，再读A1—A3相关2.3／3.2／3.6／4.1—4.5／7.2／7.4—7.8／7.14；核对git status、实际源码和目标现场后，建立docs/project/v2.01实施计划／实现进度及docs/traceability/v2.01需求实现映射，固定设计摘要与实际提交。按A1运行包→A2最终Schema→A3首环境准备→B真实装配→C真实双scope页面推进。首个批次仍是待实施，不重跑旧库初始化或占用用户服务。
- **首批调用方**：__main__.py、service.py、code_tasks/local_deployment.py、guide/worker.py、shared/http_boundary.py及requirements／documents／messages／comments真实入口；前端requirements/detail-read.ts和现有绑定／存储owner。按4.4.1验证评论索引与混合卡片入口，保留原GuideWorker、幂等、恢复和唯一持锁资格；production_options当前只构造TokenizationGateway，不在构造时读密钥／联网。
- **执行候选接续**：先读后端4.15／4.23及7.11.1／7.11.6—7.11.10、架构9.2—9.4／11.2.1。P2-a独立VM用假角色／假秘密验证来源、锁、单向proc／NNP收紧和一次交付；P2-b才接固定OpenCode与真实业务。每实例control、原pidfd／unit代次、Unix逐段凭据及原生TCP证明不能用容器ID或旧文件权限原型代替；不得放宽保护、自动重派发、增加重任务并发或默认长期fork。
- **后续门槛**：P3检查／本地Git、M管理、R维护及AUTH／AFE／REC／RCF依后端8.2推进。供应方补证按4.22.4／7.12区分原追踪ID、推理响应ID、范围与最终性；无可信证据保持只读／外发受阻。云须实际账号报价、x86平台准入、容量、Mac离线及Restic／COS取回演练；约100元预算不自动上调。原型失败只重开受影响架构决策。
- **后续授权**：普通实施检查按当时任务范围执行；真实模型／计数／供应方调用须明确次数、预算和重试边界，系统安装／服务更新、云购买、数据清理、Git提交推送与正式合入亦不从本次收口推导许可。

本记录的历史运行证据保持原日期；2026-11-20新增部分只证明设计收口及实际执行的静态核对，不代表Linux迁移、完整Agent链路或云生产完成。
