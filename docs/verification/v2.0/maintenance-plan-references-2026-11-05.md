# V2.0维护计划、元数据及登记引用

日期：2026-11-05；HEAD 28a7c9e，V2工作区未提交。仅本轮私有临时目录中的非空151副本、审计夹具及配置引用夹具；未读取正常业务库或.env.local，未更新服务／真实调用。

依据：BE 7.1.3—7.1.6全文，固定SQLite3.54.1；正式设计不自动修改。

实现：
- schema_v20_records.py以有界严格／确定JSON，同目录临时文件、flush／fsync、原生不覆盖发布及读回摘要保存原计划／追加回执。既有资产永不覆盖；失败只清理本次未发布临时元数据。
- schema_v20_references.py只登记明确配置文件和count-audit准入记录所引用的实际文档LLMUse。只保存路径／原生身份／摘要／可读性，不保存配置正文，不递归复制外部目录。自身文档引用只散列原151列，升级后仍可核对；外部证据精确150／151／200只读校验。显式重复配置拒绝；多个准入引用同一调用按已登记的同一调用处理。此处不证明供应方准入或模型效果。
- schema_v20_plan_codec.py严格解析全部字段／标量、原生身份、全旧表投影、行数／完整摘要、审计状态／顺序及引用。不接受漏表、重复表、未知字段、bool冒整数、路径重定向或伪造汇总；投影来自冻结151实际DDL。
- schema_v20_plan.py显式配置引用声明（包括明确空列表），无默认库。原源BEGIN IMMEDIATE排除SQLite其他写入者，第二独立只读连接执行Backup API；新目标在写业务字节前核对私有ACL，关闭后重新打开核验冻结151、完整性／FK及完整typed投影。全文件原字节摘要／身份、审计副本、原路径／发布／程序摘要／操作者／空间一并绑定，计划最后原子封存。源／备份／审计／配置变化拒绝，不更新旧计划、不覆盖部分资产。
- 维护源码摘要新增保留算法／ProcessLock／plan及codec；实际发布pin尚未生成。

检查：
1. 元数据／引用／audit owner／原准入四文件，tools/python-v20.py → tools/quality_python.py，19通过（66.58秒）。首次路径拼写错误只返回无测试，随后按实际guide路径执行；未把无测试算通过。
2. 计划／元数据／引用三文件，17通过、14子场景（67.05秒）。真实NTFS／DACL／原OS锁／SQLite Backup API／重开，另连接BEGIN IMMEDIATE实际被排斥；last-publication故障、篡改、源变及原计划不覆盖均覆盖。
3. python -m ruff format --no-cache --check backend/app：154文件通过；git diff --check通过。

命令：显式.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_maintenance_plan.py backend/tests/infrastructure/test_v20_maintenance_records.py backend/tests/infrastructure/test_v20_maintenance_references.py -q -p no:cacheprovider --tb=short --basetemp <本轮临时目录>，配tools.quality_gate.environment。临时包／数据库／原始输出均随专属目录清理，无测试JSON／日志保留。

未覆盖：封存演练、原库apply外层与追加回执、recover组合、CLI、真实发布pin及正常启动200接线仍待实现；低层引擎既有隔离证据见前日记录。正常库／维护窗口仍需当前具体授权；没有LPAC／Guard／供应方／前端或全版验收证据。备份与演练正常资产无自动清理策略。
