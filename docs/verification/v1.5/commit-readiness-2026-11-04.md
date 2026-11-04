# V1.5提交前核对

日期：2026-11-04（Asia/Hong_Kong）。用户明确要求先提交1.5改动。提交范围为现有backend／frontend代码、专项、v17／v18正式资源、相关工具及v1.5文档；不含v2.0资料、跨版本路线图或其导航改动。不推送、不更新服务、不操作业务数据、不调用模型或计数。

基线HEAD：8c5df4c6683e10c265e2f719a4fdc09ba4210ea0。工作区已有改动按原范围保存，未重新生成资源或合并pending设计。

本次实际检查：`.venv/Scripts/python.exe -m ruff format --no-cache --check backend/app`（125文件通过）、frontend目录`npm run format:check`及`npm run typecheck`通过，`git diff --check`通过。全局Python未安装Ruff，改用项目锁定环境0.17.3，未安装依赖。未重复全量测试／构建／浏览器；历史实际结果、失败及最终复查见[文档驱动讨论记录](document-driven-discussion-2026-11-03.md)，不能作为本轮新测试结果。

v17／v18为OFFLINE_READY，未真实供应方准入；未完成产品整版验收。现有服务未启停。本次提交仅保存已有实现与证据，2.0实施另行记录。
