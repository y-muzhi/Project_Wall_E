# 代码设置授权读取与筛选验证

- 2026-11-07，V2 工作区。设置授权分区接现有授权列表及原 ID 详情。任务 ID／状态筛选由用户提交，分页保留真实总数。列表与详情分别显示批准、绑定和生效，展示实际批准的范围，未匹配筛选与读取失败分别显示。
- 固定 SQLite 3.54.1、隔离真实 ASGI，`test_authorizations.py -k "real_native_actor_create_replay_read_filter or history_pages"`，2 项通过、21 项未选，11.00 秒。覆盖原授权批准与同键回放、实际 ID 与状态过滤、审批时间及 ID 分页。
- 前端全量 548 项通过，strict、Prettier、git diff --check 通过。Chrome 隔离生产构建 `tools/verify-v20-command-recovery.py --probe settings` 最终通过。按原授权 ID 核对未绑定与已生效两种记录、范围详情、360px 布局、无效任务 ID 不发请求、状态／任务联合过滤、无匹配、读取失败及重试。首轮浏览器定位同时匹配筛选选项与记录，按实际记录限制断言后通过。
- 浏览器全套 59 次产品 GET 和先前区域的 5 次明确写，授权区只有读取。测试浏览器、Job 及临时构建已清理。授权批准表单、绑定／环境生效业务及生产环境联调仍待。
