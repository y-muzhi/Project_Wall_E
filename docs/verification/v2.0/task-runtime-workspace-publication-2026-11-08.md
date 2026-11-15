# V2.0 执行工作区固定字节发布

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.2、原 START_INSTANCE 和首次工作区规则。 [独立迭代](../../iterations/pending/v2.0/WALL-E.首次工作区固定字节物化_V_2.0.md)

- 使用真实原私有树清单、真实 Guard 目录与普通控制方。核对实际二进制、零字节、CRLF 和嵌套目录逐字节复制，原工作区保持原字节；目的角色以原 scope／绑定和 FileID 核对。封存发布意图后逐文件只新建，完成后核对原字节、实际目标身份并保存原回执。
- 重复原请求读回真实目标；中断后只有原意图时保持未知并保留部分目标，后续不补写。已有未知目标不接管。同名同字节文件替代后读回回执不匹配。原 CHECK_CONDITIONS 和既有私有发布继续使用同一来源清单解析。
- 首次组合 17 项通过、2 项失败（83.45 秒）。现有私有记录名称白名单缺新增的原发布意图和回执文件名，补齐对应限定后缀后，3 项发布专项通过（2.62 秒）。
- 最终通过 `tools.quality_gate.environment`、临时 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 执行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`。选取 `backend/tests/code_tasks/test_task_runtime_workspace.py`、`test_task_start_conditions.py`、`backend/tests/infrastructure/test_v20_windows_task_directories.py` 和 `test_v20_windows_private_record.py`。**33 项通过**（84.01 秒），仅既有 Starlette 弃用提示。专用临时目录退出后已核对不存在。
- 282 文件 Ruff 格式、6 个改动源码 Ruff lint、`git diff --check` 通过；Git 有既有前端文件的 CRLF 提示。
- 本轮为普通用户同账户 NTFS 证据。Guard 与后端异账户时需独立部署父根并核对后端的逐级属性读取和穿越；Guard Journal 私有根保持隔离。发布组件尚待接入生产 START_INSTANCE，依据受限写入、受管配置／运行包、实际 LPAC 访问和原 Job 继续待验证。
