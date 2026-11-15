# V2.0 原请求恢复owner与传输门槛

日期：2026-11-05；HEAD 28a7c9e，V2未提交。后端用户库／正常服务／真实模型均未操作。

command-recovery.ts把程序注册的输入／结果decoder、现有ApiClient及v4 CommandRecoveryStore接为同一owner：准备先查既有intent，冻结输入后等待保存；明确发送先验证原字节／输入，再等待DISPATCHING事务完成；重开QUERY_ONLY不提交。查询只读取原回执／原operation，不派发业务或换键。明确关闭先读取原回执，再提交REQUESTED才用原key发送仅method／path；已接收事实保留ALREADY_RECEIVED，不能借关闭重放或撤回。丢回执保留原记录；确定拒绝仍查原REJECTED。202保存原task／operation，只有严格原operation终态才移入无body摘要；不把Operation.FAILED变成Task成功。

新增原身份稳定性检查、detail／receipt槽key匹配、墓碑key与摘要匹配及关闭响应method／path限定，迟到结果按原身份CAS，不覆盖新命令。实际48业务DTO必须由原入口逐一注册，未提供的绑定拒绝，不从IDB动态加载函数。原操作读取为程序提供的只读端口，实际Coding／Testing API及页面仍待后续批接入。

浏览器实际组合：tools/verify-v20-command-recovery.py --cli-entry <现有CLI0.1.23入口>，获准非AppContainer环境／真实Chrome、私有测试DB、随机127.0.0.1端口及自有Job。8组存储＋4组owner及两个真实标签均通过，最终worker退出0（4.42秒）。owner实际HTTP为显式离线响应替代：发出时从真实IDB读到DISPATCHING、关闭POST前读到REQUESTED；未知／NOT_FOUND不重发；关闭释放原intent；迟到旧读取保留新意图；202／ALREADY_RECEIVED／原operation RUNNING与FAILED；body损坏可关闭；冷启动QUERY_ONLY不可派发。未执行后端TCP业务／页面／供应方。

上述浏览器后另加stage在等待存储前冻结用户输入、blocked后禁止迟到upgrade、8MiB／真实128MiB／blocked专项。新增浏览器补验因自动审批服务HTTP403未执行；不能把此前通过覆盖这几个新增分支。现时前端离线全套478通过（5.69秒）、strict、Prettier及临时生产构建通过（1.11秒），163后端Ruff格式及diff通过。现有大包warning保留，未更新frontend/dist；全部本轮浏览器进程及临时目录已清理。

当前遗留：128MiB灌满／blocked浏览器补验、真实掉电、后端实际业务入口、原operation读取绑定及设置／任务控件。没有半成品运行进程；现有纯组件完成不等于V2或所有页面完成。

后续补验完成：审批服务恢复后，最新实际Chrome组合存储8组＋owner4组＋bounds2组及真实双标签全部通过，worker退出0／V20_IDB_BROWSER_PASSED／浏览器关闭／Job无成员及临时产物清理均确认。17份7.5MiB原体实际保存，第18份越128MiB拒绝且原17条保留；超8MiB拒绝。原生blocked事件后本owner拒绝，旧连接释放时已拒绝的upgrade中止，数据库仍version1且原两store不变。stage冻结及blocked后拒绝的新增分支本轮已覆盖；早先403仅为当次未执行历史，当前无这两项缺口。真实掉电及业务／页面仍未验证。
