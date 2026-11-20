# V2.1存储及原生状态专项（2026-11-16）

代码基线a0f4059加本轮未提交实现。检查使用隔离.venv及固定SQLite3.54.1，quality_python离线／业务数据保护；无供应方或用户业务库访问，临时目录清理。

## 实际实现

formation严格类型／命令／路线域、完整图校验；Schema210的21张形成业务表及发布标记；FormationDatabase复用原连接／事务；FormationRepository；10类原生步骤／支线／问题状态动作，同事务真实用户消息、D/F、标量／成员历史；复用原成功回执与UNKNOWN语义。尚未注册HTTP／前端，另外5类命令及其他批次未实现。

源Scope增加三个登记形成能力名。为共同源修改生成db20-r51，manifest 3a501b4152fae91d4277dfd9f7b86d482cfdee7e73b069899119a05807c3569b；SQL／Schema200合同不变，冻结r50保留。目标当前db21-r2，manifest 8a8983d499b3e7823207d5b7b92e429f7f43b983830b8ac68b5745c2f5c0a77f；合同f3f29931a176cbb64effa63fad516280120711a472f4e59a246a9683df9e0b78。r1是首个候选的历史包，当前r2固定r51。总94表；正式设计未修改。

## 检查与结果

命令：.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py backend/tests/formation -q -p no:cacheprovider --tb=short --basetemp <独占临时目录>/pytest。

52项通过，36.24秒。涵盖基础22项、Schema9项、原生状态14项、真实状态事务／回执7项。新库／源扩展对象等价、原72表保留、94表重开、源200不自动升级、包字节篡改拒绝、未知对象拒绝、同连接回滚、跨文档FK、安全引用、可延迟焦点FK、来源／发布标记不可变及freshness原因约束；状态与焦点分离、原支线事件绑定、双OPEN归属、原结果不被陈旧恢复清除；真实消息／事件／版本原子提交、同key重放、异输入冲突、NO_CHANGE不耗业务编号、审计故障全部回滚／释放认领、已持久成功但确认丢失后只重放成功。

本批中间失败：SQL构造器将表约束夹在后续列定义之前导致建库语法错误，已改为先列后表约束；测试夹具最初预期旧成功码及列占位数不符，已按实际契约修正；可延迟FK在COMMIT失败按既有Database返回CommitOutcomeUnknown，专项改为准确区分执行期IntegrityError与提交未知，没有改变原异常规则。

其他检查：ruff format --no-cache --check backend/app及git diff --check通过（发布时522源码文件）。后续新改动仍需对应检查。

## 未覆盖

尚未实现／验收完整路线COMMIT、Closure完整证据、精确CARD_RESPONSE、成果维护／复核、RecommendationBasis、AI资源及执行接入、全部读分页、HTTP和前端／浏览器；未对正常库执行升级。52项不能当V2.1全部完成。旧run9存储异常与SYSTEM Guard暂停继续保留。
