# V2.0修订后主要问题复核

日期：2026-11-04（Asia/Hong_Kong）。依据后端0.15-draft-15／前端0.14-draft-14；当前修复迭代、设计断点和两份详细正文为准，历史评审保留。

## 范围与结论

本次接续前次全文审阅，重点核对RV20-01—07及补充决定的正文修订、自然完成／用户停止、Testing就绪／失效／恢复、报告接收、错误及前端路由／分页关联；不是再次对全部第三方或产品代码开展审计。未运行产品、构建、浏览器、Windows／OpenCode／Git协议、真实模型／计数、服务或数据操作，未改设计正文、源码、资源、历史记录或提交推送。

前次七项已有相应正文规则；预登记参考项目及人工范围风险接受按本次已确认边界处理，不重新提出选择。仍发现一处会影响基本退出路径的P1契约缺口。除此之外，本次核对未再发现需要重做主体架构的大问题；这不等于已取得运行可行性或验收证据。

## MR20-01／P1：未启动任务的终止缺少可合法保存的停止证据

**确定依据：**

- 后端第532行：RuntimeBoundaryObservation要求Testing没有ManagedInstance时command_id必有；Coding的instance_id／command_id至少一项有值。唯一空关联例外限SHR-CODE-FINALIZE、带完整空清单证据的CLEANUP。
- 后端第1439、1497行：所有非终态Coding任务都可TERMINATE；原停止操作成功需要STOP观察VERIFIED。
- 后端第2305、2322行：DRAFT／READY等非终态Testing也允许终止，不依赖runner／模型已准备。
- 后端第1474行的空资源规则仍限自然收尾，未提供普通TERMINATE的STOP空清单分支。第6313行也仍以STOP核实为停止完成依据。

**可构造的正常场景：**

1. 创建Coding任务后立即终止，从未START；任务有真实CodeTask及TERMINATE操作，但没有实例／命令。
2. 创建Testing草稿后立即终止，从未RUN；没有ManagedInstance，也没有CommandExecution。
3. Testing仅执行过计划AI起草，随后终止；真实活动是后端HTTP调用，仍可能从未有受管命令。
4. 环境PREPARE在实例／命令建立前失败，用户决定终止。不能为了结束任务要求先安装Guard／启动一次程序。

**影响：** 当前字段约束无法为上述场景保存合法的STOP观察；若坚持既定成功条件会卡在STOPPING，Coding还会一直占主文档活动名额；若实现时直接跳过STOP或伪造实例／命令，则偏离现稿。该影响是根据契约推导，尚无产品运行复现。

**建议修订：** 在共享停止契约定义明确的“从未产生受管活动／原启动已可靠核清”的停止证据分支，适用于Coding与Testing及STOP／必要CLEANUP，不仅自然DELIVER。允许关联真实owner和原TERMINATE操作、instance_id／command_id为null，但必须持久核实：新派发屏障已建立；所有历史启动步骤均已核清；没有可能迟到的CREATE_SUSPENDED／RESUME／命令；后端模型请求已停止继续派发，未核清费用仍保留；已分配但未启动的权限／临时资源也按原归属核清回收。它不是用一次active=0、查无Job或超时替代证据，启动结果UNKNOWN时仍须STOPPING。

**应补验收：** Coding创建未START即停；Testing草稿／READY未RUN即停；仅计划AI后停；PREPARE未生成命令即失败后停；与首次启动竞争且回复丢失。前四类有可靠空清单／屏障证据时可终态，不造PID／命令；最后一类不能被空清单分支提前放行。两模块相同数字ID不得串归属。

## 仍需真实证据的高风险依赖

Guard／LPAC／网络／Job组合、固定OpenCode及Git协议、模型来源与主辅SSE／预算、测试driver与参考资源、200 Schema／保留升级及多页命令恢复仍按原附录准入。它们是已有的待验证事项，不作为新增设计缺陷反复列出；实施时宜先验证关键运行链路，再铺开页面。本文不授予实际安装、模型调用或服务更新许可。

## 来源与保存核对

- `docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md`：`aecdebc70a0be9ffe3b28cc4e659e36a6a53cedb5acce05f428cae262e4358d4`。
- `docs/design/v2.0/WALL-E.前端设计文档_V_2.0.md`：`3186284219579475b3c0e321be408ce133057c449f63b269bd414790396b96c8`。

本轮只新增本Markdown；保存后复核两份来源摘要未变，报告无尾随空白，本轮临时文件已清理。
