# WALL-E V2.0 未启动任务终止契约修复迭代

日期：2026-11-04（Asia/Hong_Kong）。状态：共享分支设计及静态核对完成，继续DRAFT／待实施验证。来源为用户本轮复核：Coding未START、Testing草稿未RUN时，原STOP要求实例／命令关联，空资源例外只覆盖自然CLEANUP，导致终止契约无法满足。

接续后端0.15-draft-15／前端0.14-draft-14，目标0.16-draft-16／0.15-draft-15，继续DRAFT。本轮仅7份V2 Markdown与静态核对；不改产品源码／SQL／资源／数据／服务，不执行产品／浏览器／模型／计数、安装或提交推送。前序迭代及评审／核对保持原字节，不合并V1.5正式或原V2汇总。

## 1. US20-01 共享停止分支

Coding／Testing复用同一SHR-TASK-UNSTARTED-STOP规则及原唯一TERMINATE，不创建新停止任务、实例、命令或外部执行。停止先封闭本owner派发／模型入口，递增代次，核清全部原启动步骤、在途派发者及可能迟到的原请求；已分配运行资源须按原身份收尾。没有实例／命令行、PID或Job并不是未执行的证据。

只有可靠证明从未产生所属实例／命令，且不存在未核清或可能迟到的启动、在途写入及未释放资源，才允许STOP及CLEANUP观察的instance_id／command_id／runtime_binding_ref为null；它们仍必须绑定真实task或testing_task、原TERMINATE和封闭代次，并保存完整启动屏障／资源清单证据。VERIFIED时active_process_count=0来自已证实的空执行范围，不是缺失字段默认0。

已提交给Guard的原启动nonce即使还无PID，也须在原nonce域封闭并核对；观察查无记录不能单独证明不会迟到。若后来查出真实进程／命令，则转原停止的常规分支关联真实资源；未知保持STOPPING，不能用空资源例外绕过。

## 2. 同步范围

同步RuntimeBoundaryObservation条件约束、Coding／Testing终止步骤、Guard原STOP域、SQLite200逻辑映射、运行摘要／页面文案、重复终止及重启恢复；新增验收目标覆盖未START／未RUN、部分资源准备、派发竞争、未知及跨owner。不改变原202接受／200终态回执，也不放宽有实际活动时的完整停止要求。

## 3. 完成边界

文档静态核对只证明规则、字段／映射及引用一致，不证明Windows／Guard／SQLite／HTTP／浏览器已可用。结果保存独立Markdown，设计断点保留下一步及未验证范围；本迭代继续pending。

## 4. 收口结果

后端0.16-draft-16／前端0.15-draft-15已同步SHR-TASK-UNSTARTED-STOP、运行观察空关联条件、原步骤／Guard nonce封闭、200映射及页面。没有新增业务对象／HTTP入口／账本；常规有活动资源仍完整停止，未知保持STOPPING。

新增后端6项／前端3项验收目标，累计154／106，产品执行0；文档结构／字段／接口映射及分支静态核对通过，51份保护文档、283份源码及HEAD不变，差异空白核对通过、原子临时文件0。实际摘要及未验证边界见[静态核对记录](../../../verification/v2.0/unstarted-task-termination-design-2026-11-04.md)。本轮无未完成文档改写，真实Guard／Windows／数据库／HTTP／页面仍待实施及实际验证。
