# V2.0 WFP 网络层只读预检

2026-11-08，依据 BE 7.3.2。开始条件在本地 WFP 引擎只读事务中，按 Windows SDK 固定 GUID 读取 IPv4／IPv6 的 ALE 连接、监听和接收层，并核对支持的身份及地址、端口条件。监听层按 Windows 能力使用包 SID、绑定地址和本机端口，协议限制在连接／接收层验证。只读事务结束或查询失败均释放原会话。 [Microsoft 各过滤层支持的条件](https://learn.microsoft.com/en-us/windows/win32/fwp/filtering-conditions-available-at-each-filtering-layer) [Microsoft 只读事务](https://learn.microsoft.com/en-us/windows/win32/api/fwpmu/nf-fwpmu-fwpmtransactionbegin0)

原 CHECK_CONDITIONS 单独报告本机能否读回以上层。应用对实际过滤规则、规则优先级和网络仲裁的就绪判断继续关闭，直到取得受保护 Guard 写入后原规则读回及连接证据。预检不添加、删除或重排任何规则，不申请额外系统权限。
