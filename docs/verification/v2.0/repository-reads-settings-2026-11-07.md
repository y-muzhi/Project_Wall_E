# 已登记仓库列表、详情和原观察读取验证

- 日期与代码状态：2026-11-07，V2 工作区，API03／04接入实际服务。同读快照分页并读取最近观察摘要，按原 ID 显式读取本机设置详情。列表的 root_path 为 null，详情取已登记 canonical_root，内部 Git 目录保持私有。最近 UNKNOWN／UNAVAILABLE 原样返回，无旧 READABLE 回退。
- 后端固定 SQLite 3.54.1、隔离真实 ASGI，`test_repository_reads.py`、`test_repository_operations.py`、`test_repository_observations.py`、`test_v20_frontend.py`，38 项通过、26 子用例通过，141.30 秒。核对真实空页／越界、排序、原路径投影、原观察 ID 和原操作归属、读取中止契约及正常服务入口；GET 未产生新操作、观察或任务。
- 前端新增严格 DTO，仓库设置接公共 RecordList／Pagination／EmptyState。展开详情及观察各用原 ID，选中对象变化或隐藏时取消旧读。未知观察显示原因状态，不显示空分支代替结果。全量 548 通过，strict、Prettier、git diff --check 通过，237 个后端 app 文件 Ruff 格式及两处受影响模块 lint 通过。
- Chrome 隔离生产构建 `tools/verify-v20-command-recovery.py --probe settings` 最终通过，1280／360px。覆盖仓库空态、显式详情和原观察、窄窗路径、列表失败保留和重试，并回归原请求关闭及配置身份。首轮旧夹具把所有区域空态计入待核对断言，改成对应区域后通过。全程 53 次产品 GET、5 次已验证配置或恢复写请求，仓库区域只有读取。测试进程与临时产物清理完成。
- 现有仓库业务新增 2 个读取 HTTP，累计 V2 21 个实际入口。C01／C02 业务 POST、部署环境准入及仓库写动作仍待实施。
