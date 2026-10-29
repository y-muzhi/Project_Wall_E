# 项目综合审查检查记录

日期：2026-10-28（Asia/Hong_Kong）。代码：HEAD `422cc98` 加开始时已有本地修改，业务源码本轮未修改。报告见[项目全面审查报告](../../project/v1.5/项目全面审查报告_V_1.5_2026-10-28.md)。

## 授权与范围

用户要求检查代码、文档与业务设计并形成详细报告。本轮开展只读审查及必要离线检查，使用隔离数据；真实模型／计数为0，未写用户库、启停用户服务、部署、提交或推送。既有本地变动保留。

环境：Windows／PowerShell，Node v24.15.0，Python 3.13.5，SQLite 3.45.3；复用当前已安装依赖，未安装或升级包。

## 实际执行与结果

| 项目 | 命令或方法 | 结果 |
| --- | --- | --- |
| Git 基线 | `git status --short`、`git log -5 --format='%h %s'`、`git diff --stat` | 开始时15个跟踪文件修改、3个新文档，主要为10月27日快捷键专项；未改动这些业务实现 |
| 前端全现有测试 | frontend 下 `npm.cmd test -- --test-reporter=dot` | 406 passed／0 failed／0 cancelled／0 skipped，6669.5331ms，退出0；实际输出仍为逐项文本，没有保存原始日志 |
| 类型检查 | frontend 下 `npm.cmd run typecheck` | 退出0 |
| 临时生产构建 | frontend 下 `node node_modules/vite/bin/vite.js build --outDir <本轮独占临时目录>` | 退出0，2.52s；主index约2475.73kB／gzip742.35kB，有大于500kB块提醒；未覆盖frontend/dist |
| 后端关键专项最终运行 | `.venv/Scripts/python.exe -B -m pytest backend/tests/requirements/test_v15_foundation.py backend/tests/guide/test_v15_acceptance.py backend/tests/suggestions/test_v15_bulk_accept.py backend/tests/documents/test_v15_documents.py -q -p no:cacheprovider --tb=short --maxfail=2` | **37 passed，1 warning，115.20s，退出0**；覆盖需求基础、AI接收及取消边界、批量建议决定、文档创建／确认等；不称全量后端回归 |
| 普通本地文件链接抽查 | 根README、docs/README及`docs/*/v1.5/*.md`，正则识别普通Markdown文件链接并检查存在性 | 报告生成前122份／509链接／0缺失；未查锚点、远程URL及所有归档格式 |
| 源码与资料盘点 | pathlib计数及SHA256 | 统计及正式设计摘要见报告第3章；不是全文审计证明 |
| 空白检查 | `git diff --check` | 退出0，无错误 |
| 产物检查 | `python -B tools/cleanup-test-artifacts.py --dry-run` | JSON=0，screenshots=0；只检查该工具覆盖的verification／output范围 |

最终后端运行使用`TemporaryDirectory(prefix='walle-audit-check-', dir=项目根)`，仅给子进程设置TEMP／TMP、禁用pycache和pytest缓存，subprocess设置240秒超时；输出只在内存保留，提取上述Markdown结论。完成后独占根自动清理，`TEMP_REMOVED True`。

唯一警告为当前 FastAPI TestClient 引入 Starlette 的 httpx 弃用提示。这是测试依赖兼容维护信号，不是当前测试失败；本轮没有照提示安装另一套依赖。

## 首次失败、环境调整与清理

1. 第一轮直接使用受限环境默认临时目录，数据库锁文件打开遇到权限问题，产生`2 failed, 72 errors in 4.07s`，包含建立／清理阶段错误。不能把错误总数解释为74个不同产品用例，也不能认定为37项业务逻辑失败。
2. 第二轮将TEMP／TMP设为项目根，输出5个完成标记后长时间无新增输出；人工中止，退出1。本轮没有证明该停滞的根因，不把它改写为通过。
3. 最终通过自动批准的环境访问执行相同四文件检查，使用单独临时根及240秒保护，取得上述37项通过。未改业务代码或放宽断言。
4. 第二轮中止留下`walle-v15-foundation-nka_4qbg`，核实仅含临时`v15.sqlite`及锁文件，原本轮检查PID2240／55776已退出；解析确认其绝对路径等于项目根下这个唯一目录后清理，存在性检查False。临时构建根`walle-audit-build-7yxlk573`自动清理，确认True。开始检查产生的两个零字节临时文件在后续核对时已消失。默认TEMP内按本轮夹具前缀复查无剩余目录；不操作旧记录中的历史锁目录及正常审计库。

## 服务现场

第一次受限环境端口查询未返回8000／5173，GET报WinError10013，属于访问限制，不能用来证明服务停止。

随后经自动批准进行本机只读查询：`Get-NetTCPConnection -State Listen`未发现上述端口；分别GET`http://127.0.0.1:8000/requirements`和`http://127.0.0.1:5173/requirements`，3秒超时设置，均返回WinError10061连接拒绝。结论仅为该观察时入口不可达，未诊断原因、未启动服务、未触发业务API或模型。

## 覆盖限制与接续

- 本轮为核心路径抽查，不是126个后端测试文件的全量运行。
- 没有浏览器任务验收、原生输入法验证、模型／计数请求、安全扫描或真实业务库完整性检查。
- 406前端与37后端均为本轮新结果；v15真实EV、既有浏览器专项仅作注明日期的历史依据。
- 正式设计及源码不是逐行全审；长文件按目标章节和关联调用点抽查。
- 当前人工语义、备份恢复、长文档容量、挂起请求和冷启动指标的缺口见报告H01—H12。
- 本轮未产生待实施代码，原业务断点保留；后续按新任务范围处理报告建议。
