# 文档级AI助手数据隔离检查

日期：2026-11-01；任务M15-DOC-AI-01。代码基线HEAD fed094c9f4d87f39f03f4efef142ee14b062f493，检查实际未提交工作区。规则见[独立迭代](../../archive/iterations/v1.5/WALL-E.文档级AI助手数据隔离_V_1.5.md)，正式FE／BE未合并。

## 实现与边界

保留requirement_id，Message／GuideRun新增所属document_id，CURRENT文档独立discussion_version／state，schema151。消息窗口、卡片回答、接受／续轮／重试、进展、运行／请求详情、实际Wire及私有依据／审计沿真实文档读取及写回。数据库约束拒绝跨需求／文档消息、运行及正式回答混接；需求原始描述是唯一允许空document_id的根消息，不进入默认助手历史。

前端独立文档owner、scoped API、输入／卡片草稿、读取与恢复；目标操作限定所属文档，其他文档仅经显式SourceRef只读引用。生成新文档不继承来源助手历史／进展。普通讨论不写正文，原需求级互斥保护保留。完整跨文档引用管理UI按用户“后续”边界留后续工作。

## 环境与检查结果

Windows／PowerShell，Python3.13.5使用项目.venv，锁定Ruff0.17.3及现有Node依赖。未安装依赖、未调用真实Chat或计数API；Python专项先安装quality_python守卫，拒绝外部连接、正常data和凭据访问，SQLite仅位于自有临时根。原始输出只在内存。

| 范围 | 实际命令／方式 | 结果 |
| --- | --- | --- |
| 前端离线全套 | quality_gate选择format、python-format、frontend、typecheck、build；Node预载quality_node.cjs | 447 tests／447 pass／0 fail／0 skip；该次类型先失败，最终修复与复查见下 |
| 最终类型／格式 | npm.cmd --prefix frontend run typecheck；npm.cmd --prefix frontend run format:check；.venv/Scripts/python.exe -m ruff format --no-cache --check backend/app | 全部退出0；125个后端文件已格式化 |
| 生产构建 | quality_gate临时Vite构建并清理；服务切换中npm.cmd --prefix frontend run build | 两次均退出0，正常dist已生成并由8000实页验证；仅既有大chunk提示 |
| 后端必要回归 | quality_gate.backend_files共31文件，按文件执行python -B tools/quality_python.py 文件 -q -p no:cacheprovider --tb=short --basetemp 自有临时根/pytest；4个独立进程分组 | 所选文件分批通过，包括需求、文档、人工编辑、消息／卡片、执行／恢复／取消、计数、准入、观测／评测入口、评论／建议／版本及资源审计；不声称单条完整总门禁一次通过 |
| 新隔离专项 | 上述守卫运行backend/tests/guide/test_v15_document_assistant_isolation.py | 最终7 passed／1个TestClient依赖弃用警告，45.34秒；覆盖真实SQLite、HTTP归属、A／B上下文／进展、异文档目标拒绝、显式来源、C07阶段卡片与受限清库 |
| 评测入口最终复查 | 守卫运行test_v15_evaluation_tool.py，普通短系统临时根 | 12 passed，194秒；冻结准备输入字节不变 |
| 运行时模块 | 5173实际GET api/walle、composer、conversation-owner、read-owner、detail-owner、detail-read、detail.tsx、discussion-view | 8个非空模块有预期导出，source map内容归一化后均与磁盘相等，无空转换缓存 |

前端447项的原始Markdown见[门禁记录](quality-gate-2026-11-01-210959-425566.md)。后端首轮整组240秒超时见[首次门禁](quality-gate-2026-11-01-172313-015192.md)，后改为文件分批而非扩大单条超时并伪称通过。

## 浏览器与现场

使用Playwright技能，实际RequirementDetail／WalleApi／编辑器，仅API端口由内存夹具替代。两次浏览器检查均确认A／B专属消息、两份未发送输入、独立DISCOVERY／SOLUTION进展；A发送回执丢失进入UNKNOWN，切B仍有B草稿／消息，回A原命令同文档重放，确认后只清A，B保留。最终两次POST均由夹具接收，document_id均1，未请求真实后端／模型。未选文档显示“请先创建或选择文档”，无发送入口。

夹具Console错误0，1项Vue esm feature flags警告及React开发提示来自独立编辑器夹具，不记为产品业务错误。正常8000新构建工作台显示“暂无需求”，启动占位消失。浏览器会话已close，本轮快照／Console文件及临时目录已清理。

依据用户明确“旧数据不用管，直接删除”许可，先确认原8000进程属于本项目、RUNNING运行0，再停止旧PID10452。执行tools/reset-v15-test-data.py --database 正常库绝对路径 --delete-test-data，限定data/wall-e-v1.5.sqlite，使用进程锁及原子替换重建151；清理44项旧测试计数过程数据，保留原1份准入配置。运行正常前端build后，通过.venv安全助手重新加载8000；未停止5173。

最终只读：schema_migrations为151；requirements／requirement_documents／conversation_messages／guide_runs／llm_uses均0；GET /api/v1/requirements为200且total0。8000 PID48312、5173 PID14996（仅表示检查当时）；准入检查tools/admit-v15-resource.py --database 正常库绝对路径返回LIVE_VERIFIED，使用工具内元数据假凭据且不联网。

V1.0库、配置凭据、正式资源和冻结data/v15-observation-20261024-v15-once来源保留。原schema150 SQL按HEAD原字节保存为v1_5_evidence_150.sql，仅用于只读冻结供应方技术证据；正常业务仍拒绝旧Schema，不提供迁移。浏览器存储采用新命名空间，不再恢复旧测试草稿，未擅自全站清理存储。

## 失败、修复及未覆盖

首轮后端旧夹具仍以需求级／零文档为假设，以及实际正式回答查询漏投影document_id，均已定位并修复真实路径后分文件复查。Windows长工作区嵌套临时路径使评测子进程失败，改为普通短系统临时根后12项通过；未修改冻结输入来回避断言。

前端最终门禁最初两处类型失败是composer默认scope字面量推断和浏览器夹具guide_run_id可空类型，分别明确字面量与联合类型后，strict类型及正常完整build均退出0；原失败Markdown未改写。

最后追加一次隔离7项复查使用Windows沙箱临时目录，120秒超时并遇临时目录权限；普通短系统临时根、相同离线守卫重跑7项通过，临时目录finally清理成功。检查确认未遗留该失败路径／原失败临时路径或其子进程。首次正常库只读核对误查询不存在的schema_metadata／documents表，后按实际schema_migrations／requirement_documents核对；没有因此重跑清库。

本轮cleanup-test-artifacts.py --dry-run结果JSON0／screenshots0；清除自有output/doc-ai-*、两轮浏览器日志快照，无原始测试JSON／录像／日志留存。正式FE SHA256仍039ca649799a1578d94be51d4c1b18b3e1d0e4435a659600afb65ef3a0370157，BE仍8c7bad2949d4258b37296e99d06e3747bea7e209c72974168989d749cbd8220f。源码全文件编辑均同目录临时文件fsync、并发字节核对后os.replace，没有直接覆盖空窗口。

真实供应方本轮未调用，历史LIVE准入不构成本轮语义效果／新付费授权。隔离浏览器不等于多浏览器、真实IME或所有人工编辑／归档／历史视觉验收；这些原保护由原专项与受影响回归检查。本轮无业务实现半成品，不提交推送，不自动合并正式设计。

最终静态收尾：11份本轮变更Markdown／355个本地链接目标已核对；首次发现pending迭代中的检查记录相对路径少一级，已修复后复查。唯一当前断点保持。原字节CRLF Schema在默认git diff --check中被识别为行尾空白，采用git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check确认实际空白；不改动Schema字节或正在使用的校验摘要。源码／测试／资源最终摘要26a6255e368ab6e92f98dc694d39612f93fc3f6e370ce2f1059f00aab180a012。
