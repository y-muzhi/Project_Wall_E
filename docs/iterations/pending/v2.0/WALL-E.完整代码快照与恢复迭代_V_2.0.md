# WALL-E V2.0 完整代码快照与恢复迭代

日期：2026-11-03（Asia/Hong_Kong）；编号M20-CONTENT-01；对应Q20-CONTENT；状态：设计已定／待Windows文件及恢复验证，保留pending。本文记录选择和依据；共同规格归后端，交互归前端，不形成第三份现行共同规格。

## 1. 来源与范围

按用户逐项处理未定项并“继续完成任务”的要求接续第五项。起点后端0.6-draft-6／前端0.5-draft-5，均DRAFT；前三项用户确认及Q20-MODEL保持。仅V2.0 Markdown、既有源码与官方资料静态核对，不改业务代码、资源、模型配置、数据库、用户仓库／系统或运行服务；不运行Git写入、文件故障／恢复试验、产品测试／构建／浏览器／模型／计数，不安装或提交推送。

新规则先保本文，再同步两份DRAFT；不改V1.5正式设计、原汇总、前六份迭代和旧验证。并行V1.5与EV20-01资料保留。

## 2. 采用CONTENT20-STORE-1

### 2.1 完整代码的定义与支持边界

完整是固定选择范围内的文件路径、原始默认数据流字节及Git普通文件模式，不是整个NTFS备份。保留文本编码、BOM、换行、二进制和真实空文件；不保存空目录、ACL、所有者、时间戳及系统扩展属性，不把这些元数据当代码差异。

首期支持本地NTFS常规文件；跟踪集合来自稳定stage-0索引，文件内容来自实际磁盘，含未提交修改，已删除文件在完整结果树缺席。未跟踪起点只纳入明确选择；受管工作区新增文件按固定范围纳入，不依赖gitignore。模式沿起点／已登记stage-0；新路径按new_file_mode，Windows属性不推断执行位，不能靠相似内容推断改名和模式。

纳入路径及其祖先存在链接／junction／任意reparse、硬链接多于1、命名数据流、特殊设备／离线占位、EFS等不能按本策略核验的类型则拒绝；不自动下载、解密、清理流或跟随路径。Git冲突多stage、sparse／skip-worktree、partial／promisor、gitlink／submodule、嵌套仓库及纳入文件的LFS过滤／标准指针都不准入；不fetch或把指针文本当完整大文件。已明确排除的非产品目录不遍历，不因其中内容扩大捕获。

秘密沿固定secret_policy_ref做程序路径／内容检查，不发模型。跟踪或明确选中内容命中限制即整次拒绝，不通过静默删文件继续；策略只证明登记规则命中情况，不承诺发现所有未知秘密。未取得策略资源／证据的配置不可捕获。

### 2.2 路径、范围和容量

相对路径采用UTF-8、正斜线、NFC、原大小写；拒绝绝对／UNC／设备路径、空或点段、反斜线、冒号、Windows非法或保留名、控制符、尾点／尾空格、无效Unicode与目录／文件冲突。按保守Unicode casefold检查路径及父目录别名，不把两个名字折叠成一个。源、暂存、最终及检查副本实际展开路径首期均不超过240个UTF-16单元；不悄悄改注册表或依赖长路径开关。其他路径支持另行准入。

规则product_include_paths／nonproduct_exclude_paths仅支持精确相对文件或末尾/的目录前缀，“.”只用于include表示代码根；不支持glob、否定或Shell展开。已跟踪条目自动纳入，排除规则命中任何跟踪条目则配置不适用；include只限定未跟踪／新增代码范围。目录前缀剪枝后不读被排除正文，不用排除规则隐藏已跟踪删除。跟踪文件在清单缺席与被忽略是不同事实。

固定capture_rules={content_policy_version,product_include_paths,nonproduct_exclude_paths,new_file_mode,secret_policy_ref}，version为CONTENT20-STORE-1；从起点绑定后不随普通配置切换改变。沿max_file_bytes／max_snapshot_bytes／max_snapshot_files，再增加max_capture_entries／max_capture_seconds／max_manifest_bytes，全部正值并受环境能力校验。计数按原始数据流，遍历／读取有界，超过或不可读整次失败，不留下半份可用快照。

### 2.3 自包含私有内容包

每次捕获一个独立、只由后端读写的内容包，内含repo.git、manifest.json、seal.json；不复用用户仓库对象库，不用alternates、共享硬链接或额外全局去重服务。repo.git为无工作树bare库，object_format显式等于已登记来源sha1／sha256；跨格式拒绝。精确Git可执行版本、配置隔离及交付命令仍归Q20-GIT，不能把本项当Git运行准入。

在受管私有卷内，先持久保存原操作的content_store_key和步骤，再创建本操作唯一暂存目录。原始字节经hash-object -w --stdin --no-filters写blob，mktree -z逐层形成树，不用--missing；仅接收普通blob／tree，显式排除gitlink。固定私有refs/walle/content指向根树；核对对象闭包、类型、原字节摘要、计数及清单一一对应。无checkout／hooks／过滤器／clean／smudge／EOL转换或安装程序。

manifest={schema_version,content_policy_version,capture_profile_version_id,object_format,content_tree_oid,entries,file_count,byte_count}；entry={path,mode,blob_oid,byte_count,sha256}。entries按路径UTF-8字节序排列，路径唯一；manifest用UTF-8无BOM、LF、确定键序／紧凑JSON及结尾一个LF，散列覆盖实际字节。JSON语法与数字沿现有严格工具，但文件快照不复用文档BlockState／Revision。

seal只在源最终核对、完整对象核验及文件flush完成后形成，记录原操作／资源／代次、内容规则、根树、manifest_sha256和真实captured_at；控制回执保存在受管私有区，不由AI提供。seal固定捕获完成时刻；之后源变化不把已封存字节改为“最新源”。空代码是合法空tree及0项清单，不是读取失败的替代。

### 2.4 两种捕获窗口

来源起点须用户明确确认“已暂停来源目录的编辑器保存、生成器及其他写入”；source_quiescent_confirmed必须true，属于明确操作输入，不能由程序或历史草稿默认勾选。切仓库／配置／观察／未跟踪选择、失败、重新打开或下一次捕获均重新确认；未知命令保留原body只用于查回执，不重用确认发新捕获。确认不充当未变化证据。

程序保持根／父目录身份，按句柄核对真实最终路径、卷／文件ID、类型及普通文件链接数；以只共享读、不共享写／删除的文件句柄读取并持有到封存／失败，处理现有写入映射和共享失败，不覆盖用户保存或终止外部程序。遍历前后核对完整选择、HEAD／索引标识、路径／内容摘要及模式；变化为SOURCE_CHANGED，占用为SOURCE_BUSY，范围不支持为SOURCE_UNSUPPORTED。

目录共享句柄及两遍扫描不是卷级原子快照；不能证明任意恶意并发／ABA操作下同一瞬间目录内容。本期采用合作式停止写入窗口，不安装VSS／文件系统过滤驱动，也不擅自冻结用户进程。窗口不能保证就不捕获。

候选捕获沿WIN20-ISOLATION-1，先封闭模型／新命令／写入入口、验证原角色和工具／相关服务静止，保持控制栅栏至封存；不把OpenCode idle当已停写。全部源及暂存句柄在成功／失败／取消finally释放，程序发现写入新事实即失效，不通过忙等无限重扫获得成功。

### 2.5 发布、恢复及清理

完整包封存后关闭所有Git及临时句柄，在同一受管NTFS卷内以“不覆盖既有目标”的目录重命名发布。禁跨卷copy-delete、禁替换已引用包。公开路径不存在只是观察，不是授权重建；目标已存在时核对原操作、seal和manifest，不覆盖。原文件flush和重命名不被描述为SQLite＋文件系统单一事务或绝对掉电保证。

最后短事务以capture_operation_id唯一保存CodeSnapshot／CodeCandidate及manifest_sha256，核对仍有资格时才更新current_candidate_id及控制状态。终止／换代后只可补原捕获已完成的历史事实，不开检查、不更新当前候选或恢复执行。数据库提交未知查原操作，不分配第二份内容／候选。

| 中断位置／事实 | 恢复处理 |
| --- | --- |
| 仅有准备步骤，无已封存包 | 确认无旧写入者／无发布事实后标原尝试失败或取消；用户重新确认窗口后新捕获，不自动读取变化源 |
| 暂存包已封存，目标未出现 | 验证原完整包及控制资格后只续原发布步骤，不重新读取源；停止时不新增当前结果 |
| 最终包已存在，数据库无引用／提交未知 | 核对原操作及seal／全部对象，补原唯一记录；不再次复制或更新为新源 |
| 数据库已引用，响应丢失 | 返回原身份，仅读固定内容，不重捕或重复检查 |
| 引用包缺失、损坏、seal冲突或发布结果无法判断 | CONTENT_NOT_READY／UNKNOWN，禁止开始／检查／接收／交付；不拿当前工作区修补历史 |
| 只有未封存暂存物，原进程／引用归属不明 | 保留并等待核对，不凭年龄、目录名或超时删除 |
| 已证明本操作孤儿临时物且无业务引用 | 在精确受管绝对路径核对后清理；引用内容、旧历史及其他操作目录不动 |

正常中断恢复不能证明硬件掉电持久性；重启重新核验原包，不把存在目录或HTTP200当内容完整。私有正式包没有自动过期或GC。临时包是本操作正常业务暂存，不写docs/verification；验证未来所需临时产物另行隔离清理。

### 2.6 恢复工作区、检查及阅读

首次RESTORE_WORKSPACE只从固定包在全新暂存目录构造原始普通文件，核对全清单后以不覆盖方式发布到首次工作区；不得用git checkout、copytree替换已有工作区，或先清空运行目录。目标已存在只能核对原步骤；不确定时等待，不能把后续人工／AI内容覆盖成起点。独立检查副本复用同一物化器，不链接原包；既有工作区故障不授予回滚／自动重建会话权限。

差异及文件读取始终用固定对象／清单；读取至少验证manifest摘要及被读blob的类型／长度／SHA256，首次使用／重启／进入检查或交付前验证全部闭包。损坏不给假空文件，不回读来源／工作区“补齐”。文件分页不是完整性证明；文本展示、二进制和超大部分预览沿既有前端边界。

## 3. 契约与交互影响

- 后端增加快照／候选content_policy_version、manifest_sha256、captured_at；capture规则和有界限制；原OperationStep.external_identity的content_store_key／manifest_sha256／workspace_location_key私有字段；不新建快照业务根或通用备份服务。
- CAPTURE_BASE及POST snapshots补source_quiescent_confirmed:true；新增SOURCE_BUSY／SOURCE_UNSUPPORTED明确错误，CONTENT_NOT_READY用于已引用包缺失／损坏。后台接受后的失败仍在原OperationView／WaitingItem表达。
- 创建抽屉增加本次来源暂停写入确认，未确认不能发捕获；失败显示具体路径类型或占用原因，保留选择／历史快照，不自动重捕。内容阅读说明路径／字节／模式范围，不要求用户逐个读所有文件，也不暴露私有根或打开本机文件入口。
- 前后端草稿计划升为0.7-draft-7／0.6-draft-6，保持DRAFT。后端追加TC20-61—68，前端追加TC-FE20-44—46，均为未来目标，本轮不执行。

## 4. 静态依据与未读边界

读取日期2026-11-03，采用以下一手文档相关段落，机制选择为本方案推导而非运行通过：

- [Git init](https://git-scm.com/docs/git-init)：显式对象格式；[hash-object](https://git-scm.com/docs/git-hash-object)：按原字节生成blob；[mktree](https://git-scm.com/docs/git-mktree)：NUL输入、排序和缺失对象规则；[ls-files](https://git-scm.com/docs/git-ls-files)：stage／模式和NUL路径。这里只选定对象命令用途，精确Git版本及敌对配置验证归Q20-GIT。
- [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)：句柄共享约束；[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)：句柄信息；[命名规则](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)、[reparse操作](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points-and-file-operations)、[数据流](https://learn.microsoft.com/en-us/windows/win32/fileio/file-streams)：路径和特殊类型边界。一次误用fileapi路径404后已改用winbase，未将404当OS能力不支持。
- [MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)、[FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)：同卷目录移动和文件写回；文档并不替本项目证明目录／数据库掉电事务。
- 本地ProcessLock全文及CountingJournal创建／清理分支用于复用所有权、flush与原子替换规则；documents/snapshot.py的对象／验证入口为文档BlockState，不是文件树。工具verify-frozen-git只作只读源码定位，不运行其JSON落盘工具。搜索未发现现行产品代码快照、私有Git库或Windows安全捕获实现；不把通用Path.resolve／is_symlink当已实现Win32句柄边界。

## 5. 验证与接续

静态结果保存[代码快照设计核对](../../../verification/v2.0/content-store-design-2026-11-03.md)。路径别名／链接／数据流、变化／占用／取消、seal发布／数据库提交未知、已引用包损坏、物化及掉电恢复均须后续真实Windows专项；本轮未执行。现有五项设计决定不替代运行准入。

Q20-CONTENT转设计已定／待Windows文件与恢复验证。下一项Q20-GIT：固定Git版本／环境和精确命令、私有对象转移、直接引用CAS与符号引用、外部worktree竞争、计划提交及未知结果恢复。安装、试验、真实数据写入仍需后续任务授权。
