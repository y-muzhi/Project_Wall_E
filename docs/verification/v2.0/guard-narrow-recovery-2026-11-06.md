# Guard窄恢复权限与整控制方封闭（2026-11-06）

用户已确认[窄恢复](../../iterations/pending/v2.0/WALL-E.Guard重启跨控制方恢复权限细化_V_2.0.md)，正式设计未自动合并。V2未提交；db20-r15／code20-r2未变，本批来源不在Schema SOURCE_NAMES中，不升级正常库。

## 实际实现

guard_recovery.py：重新解析当前真实peer公共头，保持当前程序保护lease；原两份私有登记须同安装／实际用户／已准入程序与包，metadata旧记录不能放行；scope／原binding（entry.job_ref）及原Registry／Journal／实际旧控制方关联。只允许OBSERVE／STOP／RELEASE。原持有进程明确EXITED，或原登记SHA匹配的持久controller-seal及全部旧scope封闭，才交出内部原scope；在途scope不等待，返回UNKNOWN。无原Registry／Job／句柄不重开旧PID，不从名字重建。权限上下文本身不执行动作，不代表停止／完整释放成功。

runtime_launch_journal.py：短全局门只覆盖私有元数据及Native派发意图，Native回调继续只持原scope门；原controller-seal阻断整个controller_ref的PREPARE／CREATE／RESUME，包括新nonce／其他Registry。封闭先发布原记录，再核对／封闭全部旧nonce；发现仍在途返回UNKNOWN，marker阻断新派发不消失。Guard重启仍读取原marker，封闭不可重开，其他controller不受影响。

GuardControllerRecords复用原PrivateRecordAppend发布固定*.controller-seal.json，绑定原登记SHA／epoch，无覆盖；丢失回执只协调相同writer／FileID／字节，不重发rename。当前Guard同时易失拒绝未知发布；marker本身不是全部scope关闭，也不是进程退出。PrivateRecordAppend只新增固定seal文件名分支，不接受任意路径。

## 实际检查与修复

普通非提升隔离临时目录／实际管道／自有Job，quality_gate.environment及tools/python-v20.py／quality_python.py，--basetemp自动清理。源码原子写入，未动正常库／服务／既有ACL或WFP／模型。

- 退出分支及前置记录／程序包三文件85通过6.71秒；权限正向为明确端口，只测试策略及scope，不当保护程序实际准入。
- 新封闭五文件120通过1失败，11.11秒。失败发生在注入“发布成功、回执丢失”后：原writer仍持有DELETE访问，读取尚未协调的marker被系统拒绝。改为显式GUARD_CONTROLLER_SEAL_READ_UNVERIFIED；先原writer协调关闭，再核对marker与尚未关闭scope，未把临时不可读或仅marker当可靠封闭。
- 修正后最终22文件413通过、1条既有Starlette弃用警告，155.31秒。范围包括全部通信／控制方／程序包／私有记录与读取包、Journal／Registry、原生AsUser、Guard崩溃、固定Git配置及两对象格式metadata真实链路。组合计数不累加。
- 223个app文件Ruff format、7受影响模块lint、git diff --check通过；cleanup-test-artifacts.py --dry-run为JSON=0／screenshots=0，无活动检查或待取回执。
- 实际封闭／重启／丢失回执使用原operator-only私有根及真实CLIENT身份；竞争的Native回调为明确可暂停端口，证明原MAY／封闭顺序与无新nonce，不冒充LPAC／SYSTEM服务。实际Guard崩溃／AsUser／Git沿已有真实组件回归。

## 未完成及下一依赖

尚无实际受保护walle-backend.exe正向准入、SYSTEM／跨用户安装、LPAC-WFP及生产Guard完整七动作派发。此处提供原权限及封闭组件，完整RELEASE还须Job／IO／固定程序／配置副本等原资源清理，release_native_handles不代表全部清理。ready／runtime_admitted=false，实际HTTP仍19条，未新增页面／浏览器或供应方证据。

接实际Guard控制方owner时，资源须独立持有原控制方进程句柄；不能因连接关闭销毁watch所借的peer进程对象，也不能按旧PID重开。下一单元用DuplicateHandle同权／不可继承副本解决原对象寿命，再接同一Guard actor的生产资源准备及派发，避免跨线程退出长期文件／程序租约。
