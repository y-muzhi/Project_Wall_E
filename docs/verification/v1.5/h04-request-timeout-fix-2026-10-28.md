# H04 请求挂起修复专项检查

日期：2026-10-28。专项M15-HTTP-01，目标软件V1.5。代码HEAD 422cc98加既有快捷键、文档整理及本专项工作区变动；无提交推送。

## 范围与结果

用户在隔离复现后要求“做个专项，修复这个问题”。本轮改ApiClient统一HTTP截止，复用原业务owner的UNKNOWN／保存核实／写屏障／轮询恢复。只有frontend/src/api/client.ts是本专项产品源码改动；新增api-timeout.test.mjs，扩展autosave、detail-read-scope、guide-composer、guide-polling测试。未改后端、资源、数据库或用户运行服务。

每次HTTP30000毫秒，覆盖响应头与完整正文；独立中止及Promise竞争确保忽略abort的传输也不锁住调用方。保留原命令与幂等键，迟到回执不采用，正常结束清理计时器及监听。保持后台AI执行时限及原正常轮询频率。

## 环境、命令与实际结果

Windows／PowerShell，Node24.15.0，现有依赖；无安装或升级。命令1—3工作目录frontend。

| 层次 | 命令／方式 | 实际结果 |
| --- | --- | --- |
| 受影响专项 | node --test --test-isolation=none tests/api-timeout.test.mjs tests/api-client.test.mjs tests/detail-read-scope.test.mjs tests/guide-composer.test.mjs tests/guide-polling.test.mjs tests/autosave.test.mjs tests/manual-end.test.mjs | 68项通过，0失败；约2.04秒 |
| 公共客户端影响回归 | node --test --test-isolation=none tests/*.test.mjs | 417项通过，0失败；约5.39秒，含新增11项H04用例；不是此前406项的历史引用 |
| 类型检查 | node node_modules/typescript/bin/tsc --noEmit | 通过，退出0 |
| 临时生产构建 | node node_modules/vite/bin/vite.js build --outDir <本轮独占临时目录> | 通过，1262模块，构建2.44秒；主包2476.23kB／gzip742.58kB；原有大包警告仍存在，不属于H04修复 |
| 原生HTTP集成 | 项目根node --input-type=module，标准输入内存脚本使用node:http临时回环服务与原生fetch，导入实际ApiClient | 3个并发真实挂起请求在30016毫秒结束，后续原键恢复通过；详见下节 |

离线测试使用虚拟时钟覆盖截止前1毫秒和截止点；响应体使用Response／ReadableStream；本地草稿存储使用测试端口，不能当作浏览器IndexedDB持久性验收。

## 原生HTTP检查的失败与复核

首次在受限环境启动本轮临时回环服务127.0.0.1:60885（PID49604），原生fetch立即连接失败，未等待到截止；“全部信号已中止”的诊断断言失败。finally关闭了该测试服务。随后独立最小回环GET证实原因为connect EACCES，属于环境网络限制，不作为产品修复通过。

经执行环境批准，在可连接本机环境重做同一检查。本轮自有127.0.0.1:62574（PID39660）只接受内存测试内容：GET headers不发送响应头；GET body发送JSON开头但不结束；POST write第一次不回执、第二次返回合法成功。三个首次请求均到达测试服务；30016毫秒后全部结束等待且本次传输信号已中止，读取／写入分别得到正确mutation类别的ApiUnknown。第二次POST沿同一ApiAction成功，服务端内存记录证明正文与Idempotency-Key相同。程序finally执行closeAllConnections和server.close，退出0。此PID和端口仅为已结束验证证据，不得用于后续启停。

没有连接8000／5173或真实供应方；不创建正常业务记录，不调用模型／计数API。本次原生Node fetch验证不等于浏览器交互验收。

## 关键行为证据

- 头／正文不返回都在单次截止后结束；正文等待沿原总时限，不另得30秒。
- 外部取消立即退出；预取消不发请求；调用方signal不被内部超时修改。
- 迟到成功不调用decoder；迟到失败不会产生未处理拒绝；未读迟到响应体取消。
- 成功、业务拒绝、网络／格式错误均移除监听并清理定时器，不在结束后发生虚假abort。
- 对话发送在超时后UNKNOWN，原输入不清除；核实后用同一键／正文恢复，一次接收运行。
- 重叠写分别在30秒／40秒结束，相关GET仅在全部结束后放行；不自动重发POST。
- 保存原请求核实成功后才提交最新编辑；旧回执不倒退确认版本。完成编辑的保存／核实读取分别超时后返回错误，不发完成命令、不清草稿，可继续编辑。
- 状态读取失败保留已确认RUNNING，显示连接错误并进入既有2秒首级退避；恢复读取终态后停止。

## 文档、清理与未覆盖

正式FE1.0／EFFECTIVE的2.2、5.5、6.1、8.2已合入；FE SHA256：eade9a6252d9fe121858c416f4fb902b970e6a47969869ae46a41dca4364a818。BE、HTTP字段、资源身份及存储结构保持。专项归档与合并记录、需求映射、实施计划、审查决定和唯一当前断点同步。

临时构建目录frontend/.tmp-h04-build-5JwtgC由mkdtemp创建；finally核实绝对路径在frontend且名称匹配后递归清理，结果不存在。原生产dist不更新。原生HTTP脚本仅标准输入／内存，无日志文件、JSON、截图或录像产物。新增测试源是可重复回归检查，作为源码保留。

未运行浏览器交互、实际用户服务联调、真实供应方或后端全量验收；后台页面节流、系统休眠不承诺严格30秒墙钟截止。多步保存核实各自有单次上限，不承诺全流程30秒。H04按源码／离线／原生HTTP范围完成；上线加载及整版验收分别处理。

最终静态复核：git diff --check退出0（只有既有换行规范提示）；本专项涉及的11份文档共357个本地链接均存在；FE／BE摘要与记录一致，待合并旧专项路径已移除，临时构建／诊断脚本目录无残留。
