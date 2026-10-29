# H04 请求挂起隔离检查

日期：2026-10-28。代码基线：HEAD 422cc98 加已有工作区修改；本轮未修改产品代码、正式设计、资源、数据库或服务。

## 授权与结论

用户在H04解释后要求“你去试试效果怎么样”。本轮只模拟请求挂起，核实影响与恢复边界；未实施修复，未调用真实模型／计数API，未提交推送。

结论：H04从静态风险升级为**已在隔离程序检查中复现的恢复缺口**。7个诊断用例全部满足断言；其中断言明确验证“仍然挂起”，所以7项通过不代表问题修复或产品验收通过。

## 方法与环境

Windows／PowerShell，Node v24.15.0。直接导入当前ApiClient、WalleApi、RequirementGuideComposer、ManualDraftAutosave、GuideRunPolling。传输注入可控未完成Promise；响应体场景使用真实Response／ReadableStream保持正文未结束。未连接项目HTTP服务或外部网络。

用node:test MockTimers替换setTimeout／setInterval并推进300000毫秒，配合微任务排空观察状态；这是**虚拟五分钟**，不是浏览器或真实网络连续观察五分钟。自动保存复用现有测试的注入时钟，并检查挂起后没有活跃重试定时器。自动保存的本地存储是记录写入的测试端口，不是实际IndexedDB持久性证明。

临时脚本位于frontend/tests/.tmp-h04-{transport,composer,autosave}.test.mjs；composer／autosave复用对应现有测试首个test前的夹具。执行命令：

~~~text
node --test --test-isolation=none frontend/tests/.tmp-h04-transport.test.mjs frontend/tests/.tmp-h04-composer.test.mjs frontend/tests/.tmp-h04-autosave.test.mjs
~~~

外层Node运行器使用spawnSync设置60000毫秒上限，并在finally删除三个脚本；各用例finally释放挂起Promise／流或AbortController并dispose控制器。只保留本Markdown，不保留原始输出、JSON、截图或录像。

## 实际结果

| 场景 | 挂起观察 | 释放／恢复结果 |
| --- | --- | --- |
| GET响应头一直不到 | 五分钟虚拟时间后仍未结束；未提供外部signal时ApiClient没有主动建立截止信号 | 注入网络失败后转ApiUnknown |
| 响应头已到、JSON正文只收到开头 | Response正文读取已开始，五分钟虚拟时间后仍未结束 | 令流报错后转ApiUnknown |
| 同一详情作用域写入挂起，随后读取 | 只发出POST；GET及waitForDetailWrites均等待 | 人工中止测试写请求后释放屏障，GET开始；没有自动重发POST |
| 对话发送挂起 | SUBMITTING、不可编辑；recover和再次submit都返回false；仍只有一次发送，原输入保留 | 注入明确网络失败后进入UNKNOWN；recover复用原Idempotency-Key及原请求正文，最终READY |
| 自动保存挂起后继续编辑 | SAVING、确认版本仍为1；允许继续输入，最新文字留在内存及模拟本地存储；重复flush不新增请求，无活跃重试定时器 | 释放第一次成功回执后，只补发最新内容一次，最终SAVED／版本3 |
| 完成编辑时保存挂起 | freezeAndFlush一直等待，accepting_input=false，编辑输入被冻结 | 收到有效保存回执后返回true |
| 运行状态读取挂起 | querying=true、connection_error=false；手动refresh只排队，没有发起第二次读取 | 对支持AbortSignal的模拟读取，隐藏再重开后可重新读取并得到COMPLETED |

结果：7 tests／7 pass／0 fail，Node测试总耗时约1.95秒；3份临时脚本全部清理。没有环境失败或修改后重跑。当前工作区其余既有改动保持。

## 解释与未覆盖

问题触发条件是请求长期既不成功也不失败；不是所有慢请求都会永久卡住，底层浏览器或网络也可能自行报错，但应用没有自己的统一等待上限。挂起写操作只阻塞共享详情读取作用域内的相关读取，不能据此声称整个应用或所有用户都不可用。

现有恢复逻辑在真正收到错误后可以工作；本轮没有观察到自动产生第二个业务操作、误报保存成功或丢失当前内存文本。不据此保证实际断电、页面刷新、浏览器存储失效后的数据安全；未检查这些场景，也未运行真实后台业务事务。

未做浏览器端交互验收、真实HTTP链路、代理／操作系统超时、后台模型任务结束时限或付费供应方调用。没有启动或重新探测8000／5173；旧端口不可达结论不是本次实验结果。

## 接续

H04：已复现，未修复，等待用户决定下一步。建议在统一传输层覆盖响应头与正文读取的截止时间；读请求转可重试提示，写请求进入结果待核实并保留原命令／幂等键，核对后恢复。不能把客户端停止等待等同后台操作取消，也不能超时后重新创建业务操作。具体时限应结合正式FE规则及后端接单方式再确定；本次未擅自改轮询频率、SSE或后台AI时限。
