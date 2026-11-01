# V1.5待合并迭代归并与提交前检查

日期：2026-11-01，D15-015。基线HEAD33a6736及此前未提交的V1.5交互代码／工具／文档。用户本次授权整理、提交推送及工作区清理；最新限定V2.0不修改、不提交且仅留本地。5份归档来源、最终规则、正式FE改前／后摘要及BE不变摘要见[合并记录](../../archive/merges/v1.5/合并记录-2026-11-01-待合并交互整理.md)。

## 本次实际范围

正式FE的原BND-DETAIL布局／操作、DT-COMMENTS呈现、BND-EDITOR几何及8.4补入最终规则；移除现行设计中的评论更多菜单、绝对工具条和失效虚线用法。5份原文顶部增加归档说明，保留原检查与失败／未覆盖；普通链接、索引、来源／决策、计划／映射／断点同步。V1.5 pending无迭代正文，后续仍先写迭代、仅用户明确要求时合入。

本轮未增加业务代码；提交内容含此前名称编辑、区块／选区／折叠、缺省内容／助手、页头入口和评论相关已完成修改。正常数据／配置／冻结资源／原始设计／服务不更改。源码及文档保存遵守同目录临时文件、flush／fsync／关闭／并发核对后原子替换。

## 实际执行的检查

- frontend下node --require ../tools/quality_node.cjs --test --test-reporter=dot tests/*.test.mjs全量离线检查退出0；不是将历史通过数累加。本批不重复原浏览器写入或真实供应方验证。
- npm run typecheck及npm run format:check退出0，strict和未使用检查保持；无新增any或忽略规则。
- Python TemporaryDirectory包裹frontend内.v15-closeout-build-*；node --require ../tools/quality_node.cjs node_modules/vite/bin/vite.js build --outDir 临时目录退出0，1.25秒，只有既有大chunk提示。临时目录已清除，不覆盖frontend/dist。
- 静态检查覆盖本工作区56份变更Markdown、768处本地链接／锚点，缺失目标／锚点均0；V1.5 pending无迭代正文、唯一当前断点，BE及冻结边界保持，git diff --check通过。最终125个暂存文件已核对：AGENTS 1、docs 55、frontend 50、tools 19；V2.0／downloads、正常数据、冻结内容、密钥及临时媒体均未纳入，敏感值模式扫描命中0，V2.0现有3份文件摘要未变；本记录不把未执行的浏览器、数据库、资源准入、真实模型／计数、部署或用户服务更新记为通过。

## Git与本地保留边界

本机两次git fetch分别遇到连接重置和443无法连接；GitHub连接器可访问且有push权限，读取master仍为33a67364d703c2b0727788d9bff61da48821ee8d。此次采用可用GitHub连接同步，要求提交树与本地index一致、父提交正确、分支快进且expected_sha核对；远端变化必须先核实，不覆盖其他提交。

V2.0设计、项目草案、V2.0迭代及downloads/WALL-E-design.md仅留本地，不暂存；仅写.git/info/exclude精确本地规则，不修改共享.gitignore。该例外不等于删除文件。最终交付提交号及同步结果以master／origin/master引用核对和Git历史为准，本记录保存提交前检查内容，不预写尚未取得的Git成功结果。

## 未覆盖与清理

原各专项的真实浏览器证据、失败及未覆盖仍保留原日期；本轮文档合并不表示整版验收。未运行后端专项（后端未改）或触发真实模型／计数，不操作正文／评论、结束人工编辑、部署、启停用户8000／5173或枚举PID。临时构建成功后清理，无本批浏览器截图／录像／原始JSON报告，正常库、审计、密钥及运行文件保留。
