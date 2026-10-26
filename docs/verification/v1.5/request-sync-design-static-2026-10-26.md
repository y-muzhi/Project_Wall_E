# 对话请求与状态同步专项思路静态核对

2026-10-26，M15-REQUEST-01。用户只要求先写专项迭代、整理思路。Git基线HEAD=a8dc673，工作区存在早前未提交实现及文档，保留；本轮只新增专项草案、更新索引／决策／计划／映射／断点，不修改业务代码或正式设计。

## 阅读及静态结果

已读根AGENTS、跨版本文档规则、当前断点／映射／索引，正式FE2.1—2.3及详情／卡片／调用记录／进展／8.4相关规则，BE版本／占用、GuideRun、C06／C07／I16及结果字段；实际相关读取与调用方、已有专项静态阅读。未完整重读所有模型指引／资源、未追溯用户这轮52条原始网络记录；没有新运行基线。

源码确认：RUNNING成功后1秒观察、失败2／5／10／30秒；run签名变化才联动刷新，不是每次成功GET都全量刷新。完整详情首尾两次摘要保护占用与版本；卡片集合可遍历历史run，已有局部pending／version缓存；调用摘要不同Provider及隐藏重开有复用空间。composer操作设置明确打开时loadBinding也可读expand=discussion，与独立进展观察分开。V1.5新run终态不沿用旧WAITING_USER。

GuideRun现有application_result／progress_result／document_effect／suggestion_batch_id等可作失效依据；不能假定changes(run)已纳入所有字段。DocumentEffect按真实document_id和前后版本；评论没有独立全集版本令牌，不能用正文版本推断评论不变。history初次读取还有恢复最近失败run用途，不能无条件删除。草案据此保留核实屏障、回退及未决测量。

[专项](../../archive/iterations/v1.5/WALL-E.对话请求与状态同步优化专项_V_1.5.md)0.1／DRAFT留pending，未合入正式设计、未实施。静态分析不等于性能优化效果；历史374项及浏览器记录未作为本轮新结果。

## 基线摘要与复核方法

正式FE SHA256=dd6f03f0464ac03f0147c8b8d6227d6de5e2837f47a3eb0702ae16b2a97a8266。

正式BE SHA256=f190d50627c90b8512c20a424cc015d72956e3e996b771e4465e230a0dd7f994。

下列22个源文件按列出顺序形成UTF-8字符串，每行`相对路径<TAB>文件字节SHA256`，LF分隔且末尾一个LF；整体SHA256=88c26ea05b64a23125f39d2980fa526c95258482d833be36bb8147de91c3e2b4。它仅固定本轮静态依据，不是冻结资源采用证明。后续按原字节重算，不以Git HEAD代替未提交内容。

- `frontend/src/requirements/detail-read.ts`
- `frontend/src/requirements/detail-owner.ts`
- `frontend/src/requirements/detail-frame.tsx`
- `frontend/src/requirements/detail.tsx`
- `frontend/src/requirements/discussion-view.tsx`
- `frontend/src/requirements/discussion.ts`
- `frontend/src/requirements/document-records.tsx`
- `frontend/src/guide/read-owner.ts`
- `frontend/src/guide/polling.ts`
- `frontend/src/guide/conversation-owner.ts`
- `frontend/src/guide/composer.ts`
- `frontend/src/guide/composer-view.tsx`
- `frontend/src/guide/cards.ts`
- `frontend/src/guide/card-groups.ts`
- `frontend/src/guide/model-call-view.tsx`
- `frontend/src/guide/model-call-reader.ts`
- `frontend/src/guide/run-actions.ts`
- `frontend/src/guide/history.ts`
- `frontend/src/messages/read.ts`
- `frontend/src/api/walle.ts`
- `frontend/src/api/models.ts`
- `backend/app/guide/contracts.py`

## 本轮执行与未执行

已执行命令类别：Get-Content／rg／rg --files读取；git status／rev-parse只读基线；SHA256；监听端口只读核实。8000／PID15852及5173／PID12440仍监听；未启停用户进程、未发送HTTP或代提交用户操作。没有模型／计数API、用户库读写、测试、类型检查、构建或浏览器运行。

最终静态检查：11份本轮责任文档232个本地链接无缺失；上述22源文件聚合摘要复核一致，正式前后端字节摘要一致；git diff --check退出0。草案188行／10747字符，明确0.1／DRAFT、pending、未实施及各项未来验收。只保留本Markdown，本轮未生成HAR、JSON报告、截图或原始日志。

静态未验证：各场景请求精确次数、重复率／字节减少、端到端延迟、取消共享读及新缓存权限边界、所有拟实施功能。状态是思路及静态核对完成，不是专项产品验收通过。
