# 固定提交基线原接收验证

2026-11-07，V2.0 工作区，Windows、SQLite 3.54.1、db20-r19。通过 tools/python-v20.py 执行隔离 SQLite、实际配置版本及原回执 HTTP。未读写真实仓库、用户数据库或用户服务。Git／内容资源由隔离目录夹具登记，当前模型和执行器未就绪。

- 原接收同时保存原操作、四步骤、预留的 CodeSnapshot ID、该 ID 对应的 refs/walle/baselines 引用和原 202。SHA-1／SHA-256 分别验证，固定输入与业务输入分开，替换为用户分支的伪造保留引用被拒。无 CodeSnapshot 占位。同键相同输入重放，改变提交冲突。错误对象格式、HEAD、零编号、缺配置及缺有效内容引用不消耗快照编号。
- 初轮六文件组合 270 通过、1 失败、5 子项通过（194.34 秒）。失败为 C05 使用通用字段验证详情写入 V2 拒绝回执，修为复用正式字段投影。最终 test_repository_baseline_acceptance.py、test_repository_acceptance.py、test_v20_command_receipts.py 共 38 项、5 子项通过（43.85 秒）。
- 因 command_registry.py 和 command_receipts.py 的受信来源变化生成 db20-r19，manifest SHA256 1c6b84ec8c07ac8c7585424e0fa1968cb122b8563c966bbcb515b35bfdc8aaba。objects.v1.json、fresh.v1.sql、upgrade-151.v1.sql 与 r18 逐文件哈希相同。245 个后端应用文件通过 Ruff 格式，改动模块 lint 和 git diff --check 通过。
- 范围限于应用接收及原命令回执。正式 C05 POST、真实固定 Git 提交闭包、创建保留引用、原未知核对、CodeSnapshot 保存及前端登记未接。
