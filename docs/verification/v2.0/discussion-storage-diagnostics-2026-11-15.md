# 普通讨论存储错误的隔离定位与诊断补充（2026-11-15）

承接用户“查一下这个问题原因”。前次事实见[run9原记录](discussion-run9-storage-diagnosis-2026-11-15.md)，本轮不改写其历史失败或用本轮结果倒推原生错误码。实施前登记[独立迭代](../../iterations/pending/v2.0/WALL-E.普通讨论存储错误诊断补充迭代V1_V_2.0.md)，保持pending，正式设计未合并。HEAD28a7c9e；本轮初始默认Git状态544条，保留其他任务改动。

## 故障调查结果

1. run9的原计数已经成功，正式LLMUse不存在，原错误STORAGE_UNAVAILABLE；未重发原消息。
2. 使用固定SQLite3.54.1、原Schema200／db20-r50、只读原库backup到独立临时副本；仅在副本重建原PREPARING／占用状态。读取原已完成计数回执，经原compile_counted核对全部实际计数文本完全一致，再调用原_prepare，副本成功建立临时LLMUse6。未配置真实计数器或Chat，未访问供应方；副本及WAL等全清理。这证明原输入及当前准备路径能通过，不证明当时没有并发或I/O故障。
3. 首次有界诊断在工具受限环境35秒超时，线程栈明确停在asyncio创建事件循环的Windows socketpair／socket.accept；此前backup所有721页已完成，副本事务重建也已完成。只结束该次自有子进程并清理副本。原普通用户环境相同诊断5.64秒通过。此环境等待不归为产品数据库锁住。
4. 旧后台没有保存内部SQLite／OS异常码，故仍不能把SQLITE_BUSY、SQLITE_IOERR、权限错误之一确认为run9的历史根因。当前数据库quick_check及准入正常，原输入准备通过；保留“短时本地存储访问异常、具体原因未确认”的结论。

## 源码及不变量

仅修改backend/app/guide/collaboration_execution.py，新增backend/tests/guide/test_v15_storage_diagnostics.py。源文件结果均内存生成，经锁定Ruff输出到内存，再同目录临时文件flush／fsync、原字节及权限复核、os.replace；不直接覆盖运行源码。

原执行链的首次准入、上下文读取、计数、计数后准入、请求准备及发送前准入／状态核对标记固定phase；StorageUnavailable／sqlite3.Error原样抛回原错误映射，只追加正常后台warning事件collaboration_storage_failure。有限异常链保留SQLite错误码／有效SQLITE名称、OS errno／winerror；不输出异常文本、SQL、参数、路径、正文、凭据或堆栈。有效范围内的日志I/O／格式错误不掩盖原失败。移除本文件原未使用GuideRepository导入，其余import排序按锁定规则。

没有更改请求内容、模型／预算、计数调用数、事务、占用、重试或失败恢复语义；没有以诊断日志代替数据库事实。该文件不在现有Schema来源pin清单，原load_release及ai-service离线检查通过，仍db20-r50，无Schema资源发布或用户库升级。

## 检查

使用tools/python-v20.py tools/quality_python.py；环境由tools.quality_gate.environment构造，明确假计数／假模型、禁止外网及凭据／正常data访问，自动TemporaryDirectory，pytest缓存关闭，输出仅内存：

- 新增4项：4 passed，10.81秒。真实第二SQLite写者冲突在PREPARE_MODEL_CALL记录SQLITE_BUSY=5，计数只一次、Chat零次、LLMUse零条、原失败及释放仍有效；计数后准入读取PermissionError记录OS errno13且敏感异常文本／路径零泄露；错误码属性边界及异常循环；日志写入I/O失败仍保留原STORAGE_UNAVAILABLE。这里的锁冲突为明确离线故障注入，不能冒充run9的已确认原生原因。
- 原执行／恢复2文件：27 passed，145.96秒，含原正常讨论／生成／修订、失败、取消及持久恢复路径。总计31项通过。
- 合并首轮将测试临时根置于data，原离线工具正确拒绝fixture访问，1 passed／30 setup errors；修正为系统自动临时根，未改保护器。随后合并检查90秒上限到期，已按本轮进程归属结束并清理，不记通过；拆分新专项及原回归后以上结果通过。
- Ruff check本轮APP／新专项通过；python -m ruff format --no-cache --check backend/app及新专项511文件通过；git diff --check受影响源码通过。
- ai-service默认离线就绪模式实际验证当前release／Schema200／db20-r50，credentials_read=0／database_opened=0／provider_calls=0。

## 实际载入与用户手动复试

22:06核对原后台PID311108／父308636及完整项目AI启动命令，现有RUNNING guide_run0、code_tasks0；只停止自己空闲的旧后台，原5173前端PID41048保留。通过原tools/ai-service.py --start载入新诊断；启动器PID131552，实际监听183580，127.0.0.1:8000。普通用户／单worker／无reload，绝对WALLE_DATABASE_PATH仍为原data/wall-e-v2.0.sqlite。

正常服务日志位于data/service-runtime-20261115-170926/backend-storage-20261115-220617.stdout.log及.stderr.log；这是用户常驻服务日志，非测试原始报告，保留运行。启动日志实际Application startup complete；前端代理GET requirements/2和后台GET guide-runs/9均200。无SYSTEM服务或Guard操作。

用户随后明确回复“已重试，成功”。只读核对：run10于香港22:07:24.548接受、22:07:38.253 COMPLETED；LLMUse6／guide_run10 SUCCEEDED，started22:07:33.357、ended22:07:38.175；新stderr没有collaboration_storage_failure。此调用由用户在页面手动发起，不是代理新调用，也不授予代理额外计数／模型许可。

当前正常使用已恢复，但run9未重现，具体历史原生根因仍未确认；不能把诊断增强或run10成功当作锁问题已修复。后续若再失败，应先读取本次后台stderr的固定阶段及原生码，再关联原run／正常计数记录，不自动重放或盲目增加重试／超时。

未保留截图、录像、临时数据库或原始测试报告。原业务库、正常审计和旧失败记录保留；无提交推送，SYSTEM检查保持暂停。
