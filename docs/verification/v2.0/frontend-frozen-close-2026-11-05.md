# V2.0 冻结命令导出／恢复与原键关闭

日期：2026-11-05；HEAD 28a7c9e，V2未提交。仅离线替代HTTP，无浏览器／用户存储／服务／真实调用。

ApiClient新增受控exportPrepared／restorePrepared，仍使用WeakMap及commit／原请求截止、同源凭据和错误边界；序列化快照不含可执行decoder／policy，恢复不生成UUID。恢复JSON必须与原prepare可产生的字节完全一致，拒绝重复键、空白变体、无效Unicode／非有限数／不安全整数及非对象，不重序列化改变原body。

code-command-snapshot.ts绑定已登记路径、当前origin、身份／body的UTF8 SHA256、8MiB上限及程序提供的输入／结果decoder；恢复重新验证，不从本地记录选择执行代码。原协作窗口Accept及带确认的Coding RESUME恢复只查，不允许submit；固定commit基线仍可按原键明确恢复。input／native函数及数组在await前捕获，外部变化不能改原请求。

code-command-close.ts及WalleApi.prepareCloseOriginalCommand通过同一ApiClient，以原key、固定控制路径和仅method／path发送；不生成关闭键或递归PendingAction。原身份有效时body损坏不阻挡关闭。CLOSED必须原FOUND／CLOSED／409；ALREADY_RECEIVED要求真实原已接收状态；NOT_FOUND／UNKNOWN无记录不能当成功。未知不重发原业务。

新增8专项，受影响三文件29通过；共享ApiClient改动后前端全套473通过（6.01秒），strict类型及npm run format:check通过，git diff --check见当前检查。仅测试程序绑定，不宣称48入口的实际业务输入／结果DTO已实现。IDB事务发送门槛、REQUESTED关闭CAS、页面及跨标签浏览器仍待接；当前底层submit不单独代表已持久保存，页面只能在后续owner门槛接入后使用。
