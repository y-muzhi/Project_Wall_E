# V2.0 后端STDIO、原控制方复制与继承白名单

日期：2026-11-05；HEAD 28a7c9e，V2未提交。仅本轮自有Job／匿名管道／命名事件及夹具，没有正常服务、业务库、设计正文或供应商秘密。

windows_stdio.py中BackendStandardIO新建6个非继承匿名pipe端，父读写端始终归后端。GuardStandardIO仅从已认证原Held控制方及其primary token租约复制3个child端，核对实际pipe类型／授予访问方向／继承位及原owner／scope，原source process重新核内核身份；不接任意文件或parent端、不读写管道字节。私有descriptor／binding不进入公共HTTP或TaskView。Native API不支持即拒绝，不猜测访问位。

后端开始交接先记录本进程MAY，未知时保留原句柄；原copy绑定可幂等确认而不能改绑，或取得原nonce关闭事实后才允许本地副本清理。它是进程内OS句柄生存期保护，不能替代业务派发记录／Guard原nonce屏障，不能当Task STOP。Guard内已复制端在原实例保持，不因后端原句柄关闭／可能数值重用而重新按descriptor复制；实际Guard ResourceRegistry／七动作调用仍需接入。

windows_job.process_creation_attributes增加明列3个STDIO的HANDLE_LIST，并同JOB_LIST在挂起创建时应用；检查确实可继承、三个不同有效句柄且不含Job控制句柄。Job、token、业务文件及其他常驻对象不通过该名单进入Root。关闭失败仅清除已成功关闭的句柄，保留原未核清owner；借用中的endpoint禁止关闭，但不以全局IO锁阻塞无关child副本释放。

实际检查：默认环境STDIO／Job22通过／2正向跳过（1.59秒）；获准普通非提升非AppContainer环境最终两文件25通过（1.23秒），无跳过。真实后端peer创建／MAY、Guard跨进程复制／类型及方向拒绝、原owner／scope拒绝；源child端释放后Guard仍持原副本。实际挂起Root已关联Job且未执行，恢复后由原后端peer写stdin并读stdout／stderr的固定三字节，Guard模块未读取数据。另一个额外可继承命名event未进入Root：先固定原句柄对象，再打开对照event并CompareObjectHandles核对，避免数字槽重用误判。

Root创建器仍为test_v20_windows_job.py的CreateProcessW测试端口；没有以复制token调用CreateProcessAsUser，不是生产Root／Guard／LPAC-WFP或完整停止验收。Source期望是实际Python worker，清理持原成员句柄，等待signaled／Job无成员后再关闭并删除专属目录。测试输出JSON只在自动清理临时目录，无残留／原始日志／截图。

专项最初50通过／1失败，Root尚未写proof：测试夹具把CompareObjectHandles误从Kernel32加载，实际应Kernelbase；已依据微软文档及实际符号探测修正。曾加的句柄比较同时防止“先OpenEvent再比旧数值”误判；未放宽继承断言。Native匿名pipe的FileNameInfo实际为空、NtQueryObject ObjectName返回不支持，因此不依赖名称、假造对象名或名字当归属证明；BasicInformation实际授予访问查询已通过。166文件Ruff格式及diff见本轮检查。

命令：WALLE_TEST_CONTROLLER_POSITIVE=1，tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_windows_stdio.py backend/tests/infrastructure/test_v20_windows_job.py -q -p no:cacheprovider --tb=short --basetemp <专属目录>，配tools.quality_gate.environment；正向仅获准环境。

来源：[CreatePipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-createpipe)、[DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)、[NtQueryObject](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntqueryobject)、[重定向STDIO](https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output)、[CompareObjectHandles](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-compareobjecthandles)。
