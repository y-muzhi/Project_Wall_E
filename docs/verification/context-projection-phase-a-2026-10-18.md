# 上下文 Token 一期专项记录

日期：2026-10-18，Asia/Hong_Kong。范围为CTX-002-A；二期／三期不在本轮。

## 当前状态

用户已明确“允许本轮离线专项与构建”。一期源码、资源及独立迭代已写入，本轮相关离线验证已完成；没有运行浏览器、真实Tokenization或Chat调用，没有启动／重启服务，没有打开或更新正常业务数据库。不能以此前TPL-003检查代替本轮验证。

## 拟执行的离线专项

- 后端：新增`backend.tests.guide.test_context_projection`，相关历史布局／模板、初始化推进、返回展示、直接确认和只读请求详情专项。
- 前端：`node --test tests/model-calls.test.mjs tests/cards.test.mjs`及`npm run build`。
- 离线资源准入：`tools/ai-service.py`不带`--start`，不读取密钥、不访问模型或业务库。
- 只在Markdown补充命令、结果与未覆盖内容，不留JSON报告、截图、录像或原始日志；隔离临时库／资源使用用例清理。

## 未覆盖

不执行真实模型效果或费用比较，不宣称实际token节省率；未实施二期长期需求记忆和任务读取，原10条历史窗口仍可能缺失更早背景。本轮不恢复全项目验收。

## 已执行及修复

- 静态检查：13份Python源码AST语法检查通过；新增Manifest的37个文件字节／摘要与两套计数绑定一致；直接改动范围`git diff --check`通过。这些检查不执行产品代码。
- 新增后端专项：`.venv/Scripts/python.exe -X utf8 -m unittest backend.tests.guide.test_context_projection -q`，首次有效执行发现通用校验器将对象键重新排序，导致稳定字段顺序与私有Basis摘要不一致。改为校验不采用其排序结果，按固定投影顺序序列化；随后9项通过（21.532秒）。另增322块字符上限及C07明确文本事实采用覆盖；C07用例修正为引用实际持久化用户content（含原规范化边界），不采用未持久化的原始末尾换行声明作证据。生产证明门禁未放宽，最终两项均通过。
- 资源加载准备阶段还发现旧v4文件数量校验误改、评论／审查转修改任务使用共享MODIFY_OUTPUT的映射遗漏，均已修正；历史v4仍31个文件，新v8为37个文件。不降低校验或回退旧协议绕过失败。
- 前端目录下`node --test tests/model-calls.test.mjs tests/cards.test.mjs`：26项通过；覆盖新诊断可空字段、旧数据兼容及既有整组卡片／直接确认行为。
- 前端目录下`npm run build`：TypeScript与Vite构建通过，1240模块，产物index-Cve-7KOc.js；仍有既有大于500KB chunk提示，未安装或升级依赖。
- `.venv/Scripts/python.exe -X utf8 tools/ai-service.py`：离线资源／实用预算准入通过，识别context_projection_v1，完整预算仍65536／131072／8192；没有传--start、读密钥、请求Provider或打开业务库。
- `.venv/Scripts/python.exe -X utf8 tools/cleanup-test-artifacts.py --dry-run`：JSON=0，screenshots=0。隔离库、计数审计及资源副本由用例清理，生产dist保留。

## 同文隔离样本的字符对比

使用原完整模板v2生成322块的隔离临时需求；保持同一正文、初始输入、读取范围与权限，分别套旧v7与新v9的传输结构，不调用计数或模型。该合成样本不是业务库调用21，不改历史请求。

|项目|结果|
|---|---:|
|旧User JSON字符数|289264|
|新User JSON字符数|102801|
|字符量缩减|64.46%|
|新任务／需求／章节索引／本轮请求字段字符合计|6938|
|实际Provider Token|未调用，未记录|

该固定夹具满足User JSON不超过130000字符、元数据与候选操作等不超过8000字符的工程候选目标；模板及所有读取块Markdown逐字保留。不据此承诺任意输入体积或实际Token节省率。

## 最终回归与收尾

1. 执行`.venv/Scripts/python.exe -X utf8 -m unittest backend.tests.infrastructure.test_full_template backend.tests.infrastructure.test_context_layout backend.tests.guide.test_initialization_progression backend.tests.guide.test_confirmed_response backend.tests.guide.test_response_display backend.tests.guide.test_model_calls backend.tests.guide.test_counted_context backend.tests.guide.test_trusted_output backend.tests.guide.test_output_evidence backend.tests.infrastructure.test_audit_repository -q`：100项组合回归，99通过、一项旧用例报错，耗时294.823秒。该旧用例在CONFIRM后仍强行编译下一次模型输入，与现行FLOW-004程序直接完成规则相冲突；修正测试辅助函数仅在RUNNING时编译，并改验正文直接写入、运行结束及LLMUse数不增加，没有改回业务流程。
2. 执行新C07用例与修正后的C06旧用例：2项通过，18.412秒。
3. 最终执行`.venv/Scripts/python.exe -X utf8 -m unittest backend.tests.guide.test_context_projection backend.tests.guide.test_initialization_progression -q`：18项全部通过，52.996秒；包含新增投影11项、初始化推进7项。该轮后仅修改注释和文档，没有再改变行为代码。不将多个运行中的重复用例累加为新的独立覆盖数。
4. Python asyncio慢任务诊断及Starlette旧httpx弃用提示不影响通过；未因此升级依赖。前端构建的大chunk提示仍为未处理项，不扩大到本轮外的打包优化。
5. 218份既有受保护资源／批准来源／原始设计文件与此前摘要基线一致；117条历史Manifest文件摘要及37条新Manifest条目检查通过。最终Manifest SHA-256为6c8e2d510b051a68363bb8a494080f1c391d98206fc25f0d4101369f0fef4d07。
6. 6份本轮Markdown的37个本地链接、尾空白及直接改动范围`git diff --check`通过；测试清理工具检查没有JSON报告或截图。隔离临时库与计数审计目录由用例清理，未留原始日志。

源码和前端生产产物已更新；本轮没有启动／重启服务，不把源码更新写成运行中的服务已经生效。没有真实模型效果、实际Token或费用比较；二期／三期、真实浏览器及全项目验收继续未覆盖。

后续授权补充：同日用户另行批准一次真实请求比较，单次实际输入125842→55946（减少55.54%），详见[独立真实观测记录](context-projection-live-once-2026-10-18.md)。上文本轮“未真实调用”指原实施及离线验证轮；后续一次观测不替代完整模型效果或费用评估。
