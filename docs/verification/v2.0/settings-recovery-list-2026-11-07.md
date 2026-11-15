# 代码设置待核对列表验证（2026-11-07）

frontend/src/code-tasks/settings 实现独立只读待核对区域，接 ApplicationRouter、主导航“设置”和实际 WalleApi／CommandRecoveryStore。首次、返回焦点和恢复网络从同 origin 原摘要查询回执，已核实 202 再读原仓库操作；完成才由已有恢复机制归档。窗口隐藏／离页取消所属读取。错误保留记录，存储失败不展示成功空态；冻结原正文不进入列表。当前只读区域不提供重新提交、关闭原键或资源创建按钮。

- 专项 21 项通过，含列表／迟到／同键读取合并／存储恢复／已接受操作／非法分区及实际路由离页保护。路由测试最初未等待异步离页准备，已等待实际异步边界后通过。
- 前端全量 537 项通过（4.06 秒），strict 类型和 npm run format:check 通过。
- 复用已有工具，以 --probe settings 运行实际生产 SPA 构建和 Chrome。真实 IndexedDB 的两份原请求，正常导航／空数据／处理中禁用及原因／多行错误／恢复／非法 section／存储 blocked 全部通过。1280×800 与 360×800 核对实际布局边界和按钮／标题不重叠。只发生 11 次产品 GET，业务写请求为 0。HTTP 回执由隔离测试服务器提供，未使用正常业务数据或真实模型。
- 浏览器脚本首次在跳转后未识别带 frame 前缀的快照引用，修正脚本后最终 worker 退出 0、OWNED_BROWSER_CLOSED、OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED。实际页面错误／空态显示正常。只保留 Markdown，临时构建、日志和浏览器产物已清理。

命令为 `tools/verify-v20-command-recovery.py --cli-entry <已安装 Playwright CLI 入口> --probe settings`。没有启停用户服务。settings 页面当前实现全局待核对区域；仓库／执行配置／检查配置／授权四分区的完整表单、原请求明确恢复／关闭、其余 V2 页面仍待实施，不能据本批构建或只读 UI 宣布整页或 V2 验收完成。
