# V2.11 进展页版本核对（2026-11-20）

- 两个工作区的 Git 指针均为 `a0f4059`。通过 `git diff e26466c HEAD -- frontend/src/requirements/discussion-view.tsx frontend/src/requirements/discussion-presentation.ts` 及工作区差异核实，当前旧进展组件与 V2.0 基线一致。旧组件最近提交为 V1.5 的 `28a7c9e`。
- 只读 GET 5174 的 `/src/requirements/detail.tsx` 实际返回 `DiscussionProgress` 导入，`/src/requirements/discussion-view.tsx` 包含「讨论主线」，`/src/formation/progress-view.tsx` 返回 404。与用户截图一致。
- 从原工作区读取本地源码确认 `frontend/src/requirements/detail.tsx` 接入 `FormationProgress`。原工作区进度记录显示 V2.1 已运行本地试用。当前库经代理请求 `/api/v1/requirements/2?expand=discussion&document_id=2` 返回 `formation_summary`，`exists=false`，步骤数均为 0。原接入以该字段存在性区分新版与旧后端，未建路线对应「文档主线尚未建立，请先在 AI 对话中讨论文档目标」。
- 以共同提交为底，按 LF 统一比较两边的前端源码、测试和工程配置，在临时目录对六个双侧修改的文件用 `git merge-file -p` 试合。原 V2.1 工作区有 82 个仅该边新增／调整或已相同的文件，另有 6 个两边分别修改的文件；其中 `api/models.ts`、`guide/composer-feedback.ts`、`guide/composer-view.tsx`、`guide/composer.ts` 需手工协调。试合结果未写回，临时目录已清理。该数量不含后台或完整版本文档。
- 本轮核对不含代码切换、新版产品验收、模型调用或数据写入，未启停服务。
