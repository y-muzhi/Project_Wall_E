# CI检查输出编码修复

日期：2026-11-10（Asia/Hong_Kong）。基线：`7faf83af1a679770545376c7ce908082f31100a7`。仅在隔离云端副本操作；未访问本地Windows项目、业务数据或用户服务。

## 原因与修改

[基线CI](https://github.com/y-muzhi/Project_Wall_E/actions/runs/42760787251)在检查程序自检通过后，父Python进程打印中文格式检查摘要时使用cp1252，触发UnicodeEncodeError并中断。子进程已有UTF-8环境设置，但不能回溯改变父进程的标准输出编码。

仅在`.github/workflows/offline-checks.yml`的离线检查步骤增加`PYTHONIOENCODING: utf-8`，让父进程启动时采用UTF-8。检查项目、命令、依赖、失败判定和业务代码不变。

## 实际检查

- `python -B -m unittest discover -s tools/tests -p test_quality_gate.py -q`：8项检查通过。
- 临时隔离回归：调用真实`quality_gate.main`，将检查命令替换为无业务副作用的成功／失败／超时探针。cp1252成功场景复现UnicodeEncodeError和中断；采用工作流UTF-8配置后，成功／失败／超时分别保持退出码0／1／1，中文摘要、Markdown报告、GitHub步骤摘要和临时目录清理均通过断言。探针及临时产物自动清理，不保存原始日志。
- YAML解析及步骤断言通过：环境变量位于离线检查步骤，原执行命令保持不变。
- `git diff --check`通过。

本地隔离检查不等于Windows完整门禁通过。此提交生成时新CI尚待推送触发；完整结果以该提交对应的GitHub Actions运行及其步骤摘要为准。未运行真实模型、浏览器验收、数据库迁移或服务更新，未合并主分支。
