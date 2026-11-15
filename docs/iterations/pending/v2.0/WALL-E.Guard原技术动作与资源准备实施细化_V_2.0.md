# Guard原技术动作与资源准备实施细化（2026-11-06）

来源：BE0.17-draft-17 7.3.1—.4原七动作幂等、资源归属回复前持久、未知仅原scope核对及7.7控制Git；接续已确认窄恢复。先写技术细化，不自动合并正式设计；不扩系统／数据／模型授权。

## 原记录与输入／输出

复用同一LaunchJournal的operator-only私有根、OS锁及原scope门，补五个有副作用动作PREPARE／CREATE_SUSPENDED／RESUME／STOP／RELEASE的原技术记录；不是WALL-E业务Operation或第二任务调度账。OBSERVE按显式observed_action读取原记录／实际资源，VERIFY_MODEL_SOURCE为受管TASK来源只读核对，不以缓存ACK替实时观察；不为查询分配新Native资源。

Native幂等域为原资源controller／action／operation／step／nonce；当前真实caller权限独立核对。已确认recovery仅改变认证caller及旧记录定位，Native摘要使用原target_scope和动作语义输入，排除认证元数据及recovery选择器，因此新调用方不会修改原Native输入／资源／nonce。旧身份不能PREPARE／CREATE／RESUME／VERIFY，公共头和权限门先落实，再使用技术记录。

首次PREPARE先持久MAY及随机预留binding_ref、directory_nonce，再创建私有包／Job／STDIO副本；同域同输入只回原记录，差异拒绝，既有MAY不重派发。CREATE／RESUME保留现Journal派发屏障，ACK只在原事实核对／持久后保存；STOP先封闭原scope，RELEASE须所有原资源完整清理，不能只关进程句柄。记录仅保存有界私有事实／摘要，不读取业务SQLite、设计正文或供应商密钥。

技术动作结果固定为冻结原JSON事实，重读给独立副本；MAY不是未执行，NO_RECORD也不证明未执行。调用方仅在首次已持久意图的本地返回中执行一次原动作，提交／回复未知只查询原记录／资源；Guard重启丢失内存原owner不重开旧PID或重建Job。普通重复请求不得在MAY后重新分配目录或Native对象。

## 部分准备和停止

原资源owner须在任何分配前进入原Guard内存归属，并记录预留引用；分配成功的每个原对象立即保留，失败／取消继续持有可清理的原对象。控制方退出／STOP同时封闭仍未形成完整Registry entry的准备步骤，禁止watch只枚举准备完成对象。准备与停止竞争须用原scope屏障，迟到对象归原owner并进入停止／释放，不从缺对象推断成功。

## 验证和边界

分批先完成原技术记录codec／确定摘要／同域／并发／失败及未知核对，再接部分准备owner和固定Typed命令。正向Native资源、端口算法、真实保护包／SYSTEM与LPAC-WFP分别记证据；不把原记录或空实现当生产七动作完成，ready=false保持。

## 固定版本探针接入（2026-11-07）

首条固定命令为 GIT20-VERSION-1。PREPARE 输入包含 run_kind、runtime_bundle_ref、command_ref 和 stdio。run_kind 为 CONTROL_GIT，包引用沿用固定 MinGit 清单。stdio 仅传 io_nonce 和三个原子端句柄。Guard 以实际当前控制方与原 scope 重建描述符。工作目录为固定程序根，单次调用持有原路径租约。输入拒绝路径、PID、命令行和环境覆盖。

CREATE_SUSPENDED、RESUME、STOP、RELEASE 的语义输入为空，窄恢复定位遵从已确认规则。OBSERVE 查询指定原动作。CONTROL_GIT 禁用 VERIFY_MODEL_SOURCE。严格解析和授权核对先于原动作记录与实际分配。

### 版本探针原动作执行

当前动作进入原 actor 前复核真实 pipe peer、当前受保护程序及原登记。跨控制方走已确认的窄恢复，保留原 scope 和绑定。OBSERVE 只读原动作、原 fence 及仍持有的资源；缺原动作或 owner 保持 UNKNOWN。原 ACK 可回放，不能代替对当前根进程的观察。STOP 先封闭原 nonce，有原 Job 则请求停止；该回执只确认已执行停止请求。无原 PREPARE 或资源时只确认 nonce 已封闭。

RELEASE 先核对原 nonce、原根退出、Job 无活动及原资源 owner。尚未满足前置条件时不接受释放意图。固定版本探针只借用共享 MinGit 路径，不创建任务私有目录；其 RELEASE 关闭原进程和外层句柄，不能删除 MinGit。后续读取命令若分配过私有目录，必须另核对该原目录已清理才能回执完整释放。

### 本机请求与原回执

每次请求使用已有受控管道帧。一帧请求最多对应一帧回复，双方沿同一原连接核对实际端点。回复固定包含 protocol_version、request_sha256、status 和 result。摘要覆盖完整规范化请求，包含当前控制方、原 scope、适用绑定、动作输入及窄恢复选择器。确认态为 ACKNOWLEDGED 或 OBSERVED；MAY 或无法核实的请求用 UNKNOWN，结果为空。回执用于关联原请求，OBSERVED 仍保留原动作状态与当前资源事实。未知结果、读写中断和回执不匹配都沿原步骤核对，不从管道失败推断未执行。请求发送层不自动重发，业务派发必须先保存原意图，后续按原操作查询。

Guard 端从处理本帧的实际 server 句柄建立原客户端租约并核对已登记程序。先验证严格头与动作输入，再进入控制方 owner 和原技术动作。旧资源路由沿同一安装的原 owner；缺少原 owner 或证据保留 UNKNOWN。协议错误或身份错误使当前连接不可用。回复不传任意内部异常文本。初始接入仅覆盖固定 Control Git，真实保护包、系统服务安装及其余运行类型按各自边界验收。

### 仓库读取私有目录释放

读取包位于原 Guard 私有根内，使用 PREPARE 已保存的目录 nonce。原准备 owner 持有实际包和固定 hooks 子目录的卷及 FileID。只有原 nonce 已封闭、Job 和原根已核清、原进程句柄已关闭，才按逆分配顺序回收；命令和配置复制文件先结束其原借用，随后清理空 hooks 及空包。Guard 关闭目录的原读租约后，只用 Windows DELETE 句柄核对同一 FileID 并标记删除。NTFS 拒绝非空目录，标记和关闭后复核原路径消失。遇到替代对象、非空、关闭失败或无法核对，保留原记录和已知句柄。不得递归删除、按名字接管现存目录、修改源仓库或删除共享运行包。

### 配置解析的原文件交接

后端以原非提升账户先持有实际 RepositoryLocationLease，再为原 config 文件取得单独的只读导出句柄，核对原 FileID、字节数与 SHA256。导出只供这次原 scope 交接，和后端自己复核原仓库所用的文件指针分开。Guard 仅从已鉴权的实际当前控制方复制同访问权的导出句柄，核对非继承、实际本地磁盘文件、原路径／FileID／字节及上限。RPC 不令 Guard 用其服务身份打开调用方给出的配置路径。配置内容只在原进程和私有临时副本中处理；回执及技术记录只保留原绑定和允许的事实。导出后的未知仍用原 scope 核对，保持原归属。

固定配置解析注册命令 GIT20-CONFIG-PARSE-1，沿 PREPARE 原意图、原 I/O、程序清单与隔离进程。其新增 config_export 仅含原文件身份、SHA256、字节数和单个导出句柄。本版 Guard 的固定配置字节上限为 1 MiB，后端仍遵守其原文件限制。控制方和 scope 由 Guard 的实际连接重建。复制权限核对 Windows 文件只读访问，实际文件及摘要须一致。Guard 在原私有读包创建空全局配置，复用同一创建、身份与释放机制；配置源为只读原句柄，复制文件及空全局配置按原归属删除。解析从原 backend STDOUT 捕获，本步骤不据进程退出声明仓库登记成功。

OBSERVE 另返回原动作已持久 ACK（如有）和仍持有的原 Job 当前成员核对。两者分别表达原回执与当前资源；未持有原 Job 时该观察为空。后端据原动作摘要恢复自己的 ACK 记录，不从旧 ACK 推断当前根或 Job 已停止。


## TASK 原封存的管道控制（2026-11-08）

沿用实际本机管道、受保护程序和当前原控制方登记。在已鉴权连接上，原私有 TASK 网络封存决定已有作用域的动作分派；请求内容不能将已有 TASK 转成 Control Git。WFP provider／sublayer 来自 Guard 启动输入，RPC 不传部署身份。无部署配置时已封存 TASK 仍归 TASK，返回 UNKNOWN。新的 TASK PREPARE 在目录／LPAC／Job 及网络端点未完成统一准入前返回 UNKNOWN，且不创建原记录或系统对象。

当前控制方可查询原技术动作、持久封闭和实际网络规则。STOP 先保存原意图并封闭原 nonce，只有确证没有 CREATE／RESUME 派发时才确认原技术封闭。若可能已有进程，仍封闭 nonce，等待实际 Job 证据。RELEASE 可回收符合条件的原网络规则，整个动作保持 UNKNOWN，网络缺失通过原 OBSERVE 读取。跨控制方 TASK 恢复保留 UNKNOWN，待其原资源及退出证明接入已确认的窄恢复。Guard 不在回复中暴露 SID、路径、WFP GUID 或端口。


## TASK 原工作区和依据封存的对象交接（2026-11-08）

以现有 START 保存的 workspace 目录、workspace-tree 文件和 basis-seal 文件为原证据。后端读取并校验原内容，短时持有同一父根及三对象的 NTFS 属性句柄。Guard 只复制已鉴权控制方的原句柄，验证对象类型、访问掩码、卷及 FileID。Guard 使用受信部署给出的父根身份以及原工作区 nonce 生成三个固定相对名称，请求不提供路径。Guard 不从这些句柄读取设计正文、内容清单或用户数据。

本批实现原来源核对。TASK PREPARE 进入经鉴权管道后，在配置了原来源根且未封闭的 scope 中核对该组对象，缺配置、对象变更或复用均保持 UNKNOWN。目录属性验证不能替代 LPAC 有效访问、依据只读副本、受管运行包／配置、入口或原 Job；原 PREPARE 在完整准入前仍不写接收记录、不分配系统资源。
