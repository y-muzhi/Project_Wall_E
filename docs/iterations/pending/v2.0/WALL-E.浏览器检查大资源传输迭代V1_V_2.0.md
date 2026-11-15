# 浏览器检查大资源传输迭代V1（V2.0）

2026-11-14香港15:41，承接实际隔离浏览器修复与真实前后端联通。当前真实前端入口JS为3187049字节；原受控转发／根回复／SDK回复每次1MiB，固定2MiB帧无法承载，受控小HTML成功不等于实际应用能加载。

复用现有同一原根／控制／匿名SDK／DevTools链，不引入另一路代理或普通用户浏览器。仅将响应body技术上限改为4MiB、控制与私有SDK帧8MiB；请求body和CasePack原输入仍1MiB，原Verification累计输出预算、状态、网络／原端点／根身份／取消／清理、64MiB DevTools技术流总量均保留。配置剩余输出不足时仍拒绝，不能截断后通过；不放开压缩、外部地址或响应头策略。跨Python组件共用根资源常量，固定CJS资源保持相同接收边界并进入manifest。

实施前已完整阅读BE7.6及原请求／响应／输出计数、read_control_frame／send_control／SDK包络。验收需：真实大响应经过同一转发及根回复，超4MiB拒绝、剩余预算不足拒绝、请求1MiB边界不变；固定SDK完整性／帧过限／原Guard结果／取消回归。最终以实际隔离浏览器打开当前编译前端及实际后端API，并验证目标监听原进程后再发送请求。测试服务只用独占新库／端口，普通SERVICE角色与正式LPAC双SERVICE准入证据分开，不启停用户服务、不调用模型。完成后保持pending，不自动合并正式设计。


15:55真实应用首轮停在大资产传输，BEGIN已到、无完整CASE／END；小矩阵仍通过，不能据此宣布真实应用成功。原Node Writable把大CDP命令一次拆为所有32KiB帧并立即回调，原根有界写队列64不能承受全部突发，后续传输／关闭可互相等待。下一步在原同一私有通道增加逐块物理写完成确认：每浏览器递增write序号，Node最多一块在途；Python原写线程完成所有短写后由原poll发ACK，Node收到同epoch／browser／write的ACK才继续下一块／完成原Writable回调。ACK仅证明原管道物理写完成，不成为权威检查结果；身份、队列限额、原输出预算、截止和取消保持，禁止通过扩大队列或假ACK绕过背压。

16:10最终技术规则已按上述原链路接入：原写线程物理写完才发ACK，SDK每浏览器仅一块在途，错误／重复／布尔序号均拒绝。4MiB响应／8MiB控制与SDK帧、1MiB请求与CasePack、128KiB权威结果及原累计预算严格分开。生产代码位于check_driver_bootstrap.py、check_driver_browser_process.py、check_driver_pipe_sdk.py、check_driver_pipe_worker.cjs、check_driver_browser_broker.cjs及OwnedBrowserRelay。没有扩大队列或另造普通浏览器入口。

最终1557固定包已通过真实隔离浏览器加载当前编译前端大JS、实际后端GET与三页导航；物理短写／ACK及超限／剩余预算拒绝等共享专项亦通过。实际结果、首次超时及测试角色边界见[验证记录](../../../verification/v2.0/browser-private-logon-2026-11-14.md)。当前为已实现并有相关离线／原生／实际应用证据，正式SYSTEM／WFP、双LPAC SERVICE及产品交付仍未验收；保持pending，未经用户要求不合并正式设计。
