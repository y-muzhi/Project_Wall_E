# 需求状态与人工编辑入口收纳检查

日期：2026-11-01。M15-MORE-01；HEAD33a6736上的未提交工作区。先写[独立迭代](../../archive/iterations/v1.5/WALL-E.需求状态与人工编辑入口收纳_V_1.5.md)，再实施header／lifecycle-control／styles。原未提交改动及v2.0资料保留。依用户最新要求，仅更新迭代和实施记录，本轮不合并正式设计。

## 实际检查

- frontend下`npm run typecheck`、`npm run format:check`退出0，strict类型及src格式通过。源码先在内存按锁定Prettier配置格式化，再同目录临时文件fsync／关闭／并发复核后原子替换。
- `node --test tests/lifecycle.test.mjs tests/manual-start.test.mjs tests/header-commands.test.mjs`：14项通过。覆盖五态独立许可、原metadata命令／目标文档冻结、UNKNOWN原请求重用、拒绝、退役及并发，不重跑全项目。
- 当前5173的requirements/header.tsx、requirements/lifecycle-control.tsx、shared/styles.css均返回200，转换大小21911／11378／96253字节；两TSX内联source map与磁盘逐一一致且有实际导出，CSS含新菜单样式且不含被替代横向动作组样式。不是仅依据HTTP200或磁盘判断。
- 独立Playwright CLI／Chrome打开需求1（原READY／IDLE、有CURRENT文档）：常驻状态标签1个，更多关闭时可见状态选择器／人工编辑入口均0；更多打开后人工编辑1个、状态选项5个；内层Esc只收起选择器，再次Esc关闭更多并返焦点；外部点击关闭。重开控件aria-controls相同，DOM保持挂载。文档区域top与height差均0px。正常阶段Console错误0、警告0。
- 浏览器先对所有/api/非GET／HEAD／OPTIONS请求安装拦截并abort，明确未转发写请求。随后通过真实控件发起状态PATCH，收起／重开后核实，2次被拦截请求的body及Idempotency-Key相同；重载读回原服务后，人工编辑入口发起1次被拦截的POST manual-draft，UNKNOWN的“重新确认开始编辑”在收起／重开后保持。全部3次写在浏览器终止，后端写入0、未捕获页面异常0。结束阶段Console的1条ERR_FAILED为主动拦截的manual-draft资源失败，不算正常阶段错误或业务成功。
- 首次用需求2验证时，等待人工编辑开始入口超时。只读核对确认它正在MANUAL_EDITING，因此原权限不再提供开始入口；没有更改占用、正文或取消编辑，改用已确认空闲的需求1完成上述检查。需求3零文档也未被用作开始编辑场景。
- 两个自有浏览器会话close均退出0；快照／日志存放frontend内TemporaryDirectory并在finally清理，不保留截图、JSON或原始日志。无新测试服务、未启停正常8000／5173。

## 边界

真实业务状态写入／人工草稿创建成功及刷新后的自动收起未在正常库执行；其命令路径由原离线专项覆盖，本轮浏览器只验证隔离的未知结果及交互。未运行生产构建、全量业务、多浏览器或真实模型／计数API，不提交推送。

正式FE SHA256保持2039cbe1e3cf5f80c9b39f40b799cfa07ae8c3633a1c6f92d84362e7c64b9b48；BE保持8c7bad2949d4258b37296e99d06e3747bea7e209c72974168989d749cbd8220f。收尾实际核对9份文档／362条本地链接与锚点通过，当前断点唯一，AGENTS及文档管理的新规则已核对，原子／浏览器临时产物0；git diff --check通过。
