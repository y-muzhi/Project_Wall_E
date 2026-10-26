# WALL-E V1.5 嵌套空字段与来源标记指引修复

2026-10-24。正式BE共同Prompt及原严格Schema／C07的增量落实，不新增业务对象、权限或模型调用。

真实v14技术＋26EV已完整结束：29计数／25Chat、总265572 Token，零重试。19份EV validation成功、3份分量拒绝、2份真实8192截断；两份必要全文0Chat，6个候选后处理PASSED。原3个失败分别为两领域生成时把自由文本标为USER_DECISION、实验耗材初始讨论的CLARIFICATION卡片省略action_payload=null。程序保护符合现有规则，正文和合法进度分别保存，原失败不回写。

修复：正式Prompt第四段说明required对每层对象有效，具体指出CLARIFICATION的action_payload必须JSON null；自由输入的偏好、纠正及明确生成请求仍为USER_STATEMENT，不影响原话约束或current_request.operation的生成授权，不误作正式卡片采用。USER_DECISION必须有实际formal_answers／dispositions来源。追加v15 Prompt v6／release v7，Schema、Wire、预算和C07仍原样，不自动补字段或放宽来源。

同时补评测执行器的已发现停止缺口：ModelGateway可将超时／网络失败返回为TransportResult失败而不抛异常，运行本地终态不代表远端结果已知。原执行器只核对RUNNING／计数异常／SUSPENDED，可能继续下一独立样本。新额度包装标记失败或缺失传输证据，记录当前样本后停止整批；成功HTTP外壳内的无效／自然截断内容仍按独立EV样本记录，不把它当未知网络。此缺口本轮未发生，25实际Chat均SUCCEEDED，不改写v14结果。

原v14执行器14423b11bb44afe2f3e8723e41409e9010820a963e70bd730552707f51f45fbb以原始字节保存sources/v1.5/run-v15-evaluation-v14-frozen.py及.gitattributes，不复制原始JSON或审计。新执行器21bfb89a…；定向5 passed／36.53秒，相关9文件108 passed／528.28秒，资源、C07、进度、卡片、计数、准入、观测、EV停止与正常26流程、请求详情均通过。原112个v14真实证据及v9—v15资源哈希复核未改；v15相对v14其余19资源同字节。完整命令及边界见nested-null-origin-v15-offline-2026-10-24.md。下一新版真实调用仍须新明确许可，不续用v14上限，不把离线通过称供应方通过；本迭代已合入正式Prompt并归档。
