# V2.1实施前检查（2026-11-15）

代码基线：隔离工作区codex/v2.1-design-review已快进到a0f40592702cb702ed928849ac540479c22c224f；保留原V2.1待合并文档。没有产品改动、提交或推送。用户已明确保留两项旧版已知事项继续V2.1实施。

## 范围及环境

使用当前工作区独立.venv及frontend/node_modules；来自本机已有锁定依赖，不联网安装，不共享运行目录。Python3.13.5、Node24.15.0；固定SQLite3.54.1。检查使用quality_gate.py／quality_python.py／quality_node.cjs的离线保护及独占临时目录，不读取正常业务库、密钥或触发真实供应方。检查结束清理临时数据库／构建输出，仅保留本Markdown。无本轮服务进程；没有更新用户服务。

## 实际结果

| 检查 | 命令／范围 | 结果 |
| --- | --- | --- |
| SQLite及发布 | .venv/Scripts/python.exe -B tools/python-v20.py --probe；activate后load_release | 固定运行时通过，db20-r50加载通过；contract 62eeeaee0ce469548abc4b4916a39c41dd28e2040b2c88c8ff035203988540c5 |
| 原DDL一致 | r48／r50 fresh.v1.sql SHA256 | 均9da3375bcaed99e9b492f4fda04119eef78dcc5784c2b5daf13ac118f28957ad |
| 后端排版 | python -m ruff format --no-cache --check backend/app | 通过 |
| 前端排版／类型／构建 | npm run format:check；typecheck；Vite build到临时目录 | 均通过 |
| 前端专项 | node --test tests/*.test.mjs（完整现有集合） | 576／576通过；最初因隔离.venv尚缺失失败1项，补齐本地环境后全过，无产品修复 |
| Schema回归 | tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_schema_state.py backend/tests/infrastructure/test_v20_schema_release.py -q -p no:cacheprovider --tb=short --basetemp <临时目录> | 9通过、3子测试通过；2.63秒 |
| 评论回归 | 同上runner，backend/tests/comments/test_v15_comments.py | 4通过；14.15秒 |
| 讨论／存储回归 | 同上runner，backend/tests/guide/test_v15_execution.py及test_v15_storage_diagnostics.py | 25通过；138.96秒 |
| 差异空白 | git diff --check | 通过 |

后端测试保留1条FastAPI/httpx弃用警告，不在本次升级依赖。旧V1.5 gate默认33文件／210声明测试未获得完整通过：240秒超时；受限环境最初连最小asyncio探针也超时，正常权限探针通过后相关异步专项使用正常权限重跑。首次超时清理遇taskkill超时，之后按本轮唯一临时目录核实无遗留进程并清理；第二次超时正常清理。不能把超时写成测试断言失败或全量通过。

## 保留事项与结论边界

V2.0普通讨论run9曾存储失败，原始根因未定位；后续run10成功。本轮相关25项离线通过不能证明已解释该历史事件。SYSTEM Guard真实验收仍暂停。用户选择保留这两项继续实施；不恢复该验收，不进行额外真实Chat／Tokenization。

本轮没有发现新的编译或上述专项断言失败，足以继续隔离区实施；不代表全量验收通过。V2.1执行Schema、存储、业务接入、浏览器及供应方证据均待实施后取得。
