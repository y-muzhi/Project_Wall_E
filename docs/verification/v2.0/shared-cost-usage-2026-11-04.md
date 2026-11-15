# V2.0共享金额与用量基础单元

日期：2026-11-04（Asia/Hong_Kong）。代码基线HEAD 28a7c9e（本轮按用户要求先保存1.5，129文件，未推送）；以下2.0文件尚未提交。实现按BE 0.17-draft-17／FE 0.16-draft-16的原有规则，不改变设计状态或业务规则。

## 范围与实现

- backend/app/code_tasks/costs.py：Money／CnyBalance解析与六位输出；精确可用余额；最高适用价格／已证明Token上界的向上预留；互斥缓存类别、总额一次半值向上结算。缺最终input／output或价差缓存维度时拒绝核算；同输入价情况下允许仅使用完整总输入。reasoning不另加费用。
- backend/app/code_tasks/usage.py：按原响应累计、缺失不补0、同帧子集检查、最终来源与完整结束／审计约束、冻结终值及重复／冲突。final_usage_cost连接终值与费用函数，PARTIAL／DISPUTED不能计算。
- frontend/src/api/code-values.ts：独立Money／CnyBalance decoder、BigInt精确微元、预算快照字段与余额一致性核对；-0.000001保留，不钳制为0。严格复用既有shape／text／count。
- 后端包／测试与前端专项为新增文件；未修改既有1.5业务入口、冻结资源、数据库Schema或锁文件。全部源码／格式结果均同目录临时文件fsync、关闭、原字节并发复核、os.replace，成功失败清理。

输入是已准入的适用价格／缓存规则和已证明来源；纯算法不能生成这些证据。UsageState不是第二份账务或审计；未来原帧先持久化，原LLMUse／Reservation数据库唯一关联负责只结算一次。

## 实际检查

| 命令／环境 | 结果 | 边界 |
| --- | --- | --- |
| .venv/Scripts/python.exe -B -m unittest discover -s backend/tests/code_tasks -v | 最终15项通过 | 设计6个定价向量、超浮点精度、负余额、严格输入／缺项／缓存，100→150→200累计及重复／回退／跨响应／终值冲突，累计→终值→费用实际函数调用 |
| frontend目录node --test tests/v20-code-values.test.mjs | 3项通过 | 精确微元、非法文本／负零、严格预算快照、负余额与字段缺失／多余 |
| frontend目录npm run typecheck | 通过 | strict与未使用变量／参数保持开启 |
| frontend目录npm run format:check | 通过 | 当前全部src |
| .venv/Scripts/python.exe -m ruff format --no-cache --check backend/app | 最终128文件通过 | 首次costs.py两处排版不符，生成内存格式结果并原子替换修复，未直接覆盖运行源码 |
| git diff --check | 通过 | 另核对新增文件；无JSON报告、截图、原始日志或本轮临时文件留存 |

首次金额专项为6后端／3前端通过；补用量和实际函数连接后最终15后端，重叠轮次不相加。最终前端检查若无相关修改不机械重跑。没有生产构建或浏览器：本单元未增改页面／组件／样式／路由或启动开发服务。没有外部网络、模型／计数、业务数据、用户Git引用、服务启停或更新。

设计摘要：BE 1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37；FE 38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7；与读取时一致。

## 未覆盖与接续

尚无HTTP／WalleApi／页面调用、SSE实际解析器、LLMUse／帧／Reservation存储、数据库一次结算、发送与停止控制；不能宣称产品调用预算已可用。固定OpenCode、Guard／Windows、Git、价格、检查包、供应方及端到端仍按设计默认未准入。首个P0单元可独立检查完成，整体P0及B1—B3未完成。

当前.git/info/exclude已排除docs/design/v2.0、docs/project/v2.0等本地设计资料；未修改用户排除规则或强制加入暂存。新实施计划与当前断点已实际保存对应本地目录，后续如提交2.0，应核对这些排除规则及完整提交范围。当前唯一实施断点见[实现进度](../../project/v2.0/实现进度_V_2.0.md)，能力状态见[映射](../../traceability/v2.0/需求实现映射_V_2.0.md)。
