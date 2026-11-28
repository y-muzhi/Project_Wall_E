# V2.2 开发站切换与回退隔离演练

2026-11-27（香港时间）。Windows，独立候选检出 `.tmp/v22-document-ai`，提交 `990ed2d` 叠加既有文档 AI 工作区修改。使用项目固定 SQLite 3.54.1、项目 `.venv` 解释器和 Node v24.15.0。验收入口和正式操作顺序见 [切换当天清单](../../operations/v2.2/开发站切换验收与回退_V_2.2.md)。

| 范围 | 本轮结果 |
| --- | --- |
| 前端握手与草稿 | `node --test frontend/tests/environment-binding.test.mjs frontend/tests/manual-recovery.test.mjs`，29 项通过。覆盖入口与握手配对、错代次、原会话冻结、草稿分歧保全、连接重查、开发编辑角色和恢复只读。使用模拟入口及网络。 |
| 固定结构 | 从候选目录运行 `../../.venv/Scripts/python.exe -B tools/python-v20.py -m pytest -q -p no:cacheprovider --basetemp <短路径临时目录> backend/tests/infrastructure/test_v22_candidate_schema.py`，2 项通过。覆盖候选来源摘要、新代次绑定、保留行篡改后拒绝重开，以及新建库。首次系统临时目录过深，Windows 在复制固定来源时找不到长路径，改用工作区 `.tmp` 下的唯一短目录后通过。 |
| 数据换代与回退读回 | 用相同解释器通过 `-B -` 执行一次性探针。复用现有业务测试夹具，以正式需求、文档及草稿命令生成已发布正文、2 条修订和一份以第 2 版为基准的未提交草稿。用 `mode=ro`／`query_only` 备份到目标，再用 `extend_document_ai_copy` 转换。目标的正文、草稿及修订业务查询逐项等于源基线。目标拒绝旧代次、集成绑定和旧结构。重新以旧结构和原代次打开原库，三项业务查询仍等于基线，原库拒绝目标代次。独立集成库逻辑转储一致。探针首次因固定 SQLite 导入顺序和夹具标题过长终止，修正二者后通过。 |
| API 权限与停止条件 | 用同一解释器通过 `-B -` 直接调用生产 `environment_http.api_admission`，以合成身份和内联执行替代安装身份读取与线程调度，后继路由使用探针。9 项通过。开发编辑指引 GET 放行，开发只读、集成及外发暂停状态的同一路由返回 403，恢复期返回 `RECOVERY_READ_ONLY`。只读写入返回 `ENVIRONMENT_ACCESS_DENIED`。旧代次和错环境分别返回对应 409，均未到达后继路由。集成普通列表仍走其自己的路由。响应头环境与代次匹配各自安装夹具。 |
| 宿主受管与 ASGI | 本轮 Windows 的持久选择守卫 3 个子用例因缺少 `fcntl` 跳过。包含完整 ASGI 文档 AI 与同结构管理用例的组合运行停在 ASGI 用例，取消后未取得这些用例的本轮结论。用于 API 准入的异步探针也未完成，改用同步驱动无挂起的准入协程后取得上述 9 项结果。既有 [Mock 应用往返](document-ai-development-roundtrip-2026-11-27.md) 留作历史证据。 |

本轮通过重新打开隔离原库演练数据侧回退。实际受管关闭、选择、HTTPS 切回、回退后控制结算及有新写入时的反向保全链仍待证明。缺少实际执行与回退证据时应在清单的开始条件停止。Mac 双站现场状态以切换窗口的新观察为准。既有双站基线、只读副本及部署预览提供对照。[双站能力基线](mac-linux-ai-capabilities-2026-11-27.md) · [只读副本恢复](document-ai-recovery-copy-2026-11-27.md) · [部署预览](document-ai-deployment-preview-2026-11-27.md)

未访问运行中业务数据、修改站点或发出模型及计数请求。成功、失败及取消留下的本轮短路径夹具均已清理，无原始结果文件留存。正式双站 HTTPS、真实浏览器旧标签、受管切换及真实供应方验收仍待执行。
