# V2.0 WFP 原任务规则与读回核对

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，隔离 SQLite 3.54.1／db20-r29。范围为 Guard 内部网络规则准备和只读核对。 [独立实施细化](../../iterations/pending/v2.0/WALL-E.WFP原任务规则与读回核对_V_2.0.md)

- 原 TASK PREPARE 提供原控制方、代次、作用域、原输入摘要及两项分配引用。按原控制方的私有 NTFS 记录封存四类回环端口和部署 provider／sublayer；无覆盖、原字节相同才可重用。先有 STOP 请求、关闭原 nonce 或已确认而没有网络清单时拒绝新封存。Guard 关闭并重开实际私有目录后，可按旧作用域和原代次从同一封存重建只读规则；换代次或部署引用则拒绝。读取方法仍须由 Guard 授权原控制方或窄恢复调用。
- 用真实 SID 推导及固定 Windows GUID 生成原规则。IPv4／IPv6 的连接、监听、接收都有按任务 SID 匹配的持久默认拒绝，精确允许限授权角色的回环地址及端口；支持协议条件的层额外匹配 TCP。只读事务逐键核对 provider／sublayer、所有者摘要、规则条件、动作、持久标记及权重，任一变化即拒绝。 [微软规则结构](https://learn.microsoft.com/en-us/windows/win32/api/fwpmtypes/ns-fwpmtypes-fwpm_filter0) [微软仲裁](https://learn.microsoft.com/en-us/windows/win32/fwp/filter-arbitration)
- 首轮封存夹具只有普通目录身份，Native 写入拒绝，已改为真实 owner-only NTFS 包。正向过滤器读回使用内存 ABI 夹具；另执行真实本机 Windows API，在未安装测试规则时保持拒绝。未安装、删除或重排任何机器规则。
- Guard、WFP 与 START 组合 52 项通过（88.64 秒）。追加 STOP 屏障和重启读取后最终 Guard／WFP 专项 21 项通过（1.82 秒）。应用 Ruff 277 文件格式、改动文件 lint 和 Git 空白检查通过。隔离临时产物已清理。
- 受信 Guard 系统服务上的规则写入、额外匹配规则及跨子层仲裁的完整核对、真实连接、接入完整 TASK 派发和停止后的 WFP 资源释放仍待。当前执行准入保持关闭。
