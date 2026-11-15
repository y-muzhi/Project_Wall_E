# V2.0 基线详情与文件分页验证

2026-11-08。工作区、Windows NTFS、锁定 SQLite／MinGit，隔离仓库、数据库、实际 Guard 管道和后端 ASGI。Schema db20-r21，manifest SHA256 032eaf32c7b1b7684224d1c27145783b9e6992be7704661ac01ef298834d048b。r21 仅因 service.py 接入路由及错误契约重建固定来源，objects.v1.json、fresh.v1.sql、upgrade-151.v1.sql 与 r20 的 SHA256 完全相同。

- 真实原提交查询专项通过。已有快照通过新的私有 CONFIG／OBJECT_BATCH 查询固定根树，从有未提交修改的仓库返回原提交条目。缺引用时无新 Guard 执行范围。查询前后操作、步骤、快照及幂等记录逐行相同，原工作区与 Git 内容不变。
- 跨后端真实退出恢复专项通过。查询在旧对象读取范围未释放时退出，新后端只对原范围 OBSERVE／STOP／OBSERVE／RELEASE，关闭私有查询记录，原登记保持成功。C05 原写入跨后端恢复在 r21 也通过回归。
- 实际 API06／19 HTTP 专项通过，验证详情、固定文件第一页、越界真实空页、暂缺引用时详情不可用／文件页 409、非法重复参数 422、原快照不存在 404。初次 HTTP 联测发现 CONTENT_NOT_READY 缺既有冲突详情，补上原 SNAPSHOT 身份后复测通过。
- 后端仓库、幂等、元数据、固定发布等回归 74 项通过，另两项实际 ASGI 核对历史结果和关闭 Guard 后读取的处理。前端最终 555 项测试、类型、格式及隔离 Vite 构建通过，新增固定快照与文件 API 绑定及 UTF-8 路径排序核对。
- 客户端断开信号专项通过，原读取收到取消信号；加入监测后，实际详情／分页／缺引用 HTTP 专项再通过。静态格式、lint 和 diff 检查通过。默认权限运行一次取消专项未返回，已定位并结束该隔离测试进程，受控隔离复测通过。
- 读取使用原注册步骤和私有查询计划，专用线程最多排队 8 项，已关闭计划保留为审计。当前实现以每安装 100000 份计划为上限，达到上限时明确拒绝新查询。发布只更新工作区的固定资源版本，正式部署、真实账户及业务库升级未验证。

## 命令及覆盖

Python 使用 .venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/quality_python.py，临时环境由 tools.quality_gate.environment 提供。实际 Git 与 HTTP 在 test_v20_guard_control_git_transport.py 中按 BASELINE_QUERY、registered_snapshot_http、restarted_baseline 选择。后端回归覆盖 test_v20_schema_release、test_v20_git_repository_metadata、test_repository_baseline_acceptance、test_repository_acceptance、test_repository_operations、test_repository_git_dispatch。前端使用 npm run typecheck、npm run format:check、npm test 和隔离的 Vite build。

此批为 API 和客户端，任务创建页面、实际生产安装与长周期容量验证待后续。
