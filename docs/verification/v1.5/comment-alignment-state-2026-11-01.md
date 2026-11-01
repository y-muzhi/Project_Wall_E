# 评论按钮禁用状态与头部对齐检查

日期：2026-11-01。M15-COMMENT-ALIGN-03，HEAD33a6736上的未提交工作区。先写[独立迭代](../../archive/iterations/v1.5/WALL-E.评论按钮状态说明与头部对齐修正_V_1.5.md)，再改4个src文件、1个专项及AGENTS规则；正式设计不合并，原其他改动和v2.0资料保持。

## 原因与修复

用户截图处于人工编辑。前端writeReady被MANUAL视图／工作占用阻止，后端comments.commands._mutate对编辑／解决／重开／删除共同执行assert_idle；灰色原生disabled按钮原本就不会发命令。旧面板提示仅提新增、按钮title只写操作名，缺少对评论维护暂停的准确说明。本次保留真实权限，面板明确说明人工编辑期间不能新增／编辑／解决／删除，先完成或取消编辑并返回正式正文；禁用按钮与外层悬停槽的title、aria-describedby使用同一真实原因。暂停、历史、归档、AI／批次及未就绪分别按实际原因说明。

旧工具条独立position:absolute/top/right且引用用92px padding避让，按钮中心与引用首行无共同约束。现抽出CommentCard，以grid把引用和工具宿主自然分列；引用首行28px基础高度（24px行高＋上下2px），工具按钮28×28，图标居中。CardActions通过项目既有Portal模式挂到头部，保留单一操作／恢复owner；正文／评论原文不变。删除旧绝对定位和右侧补白，长引用不覆盖工具条。AGENTS新增真实宿主／实际状态及宽窄多行检查要求，不把格式或空闲示例当完整验证。

## 实际检查

- frontend下`npm run typecheck`、`npm run format:check`退出0，strict及锁定格式通过。
- `node --test --test-reporter=spec tests/comments.test.mjs tests/comment-panel.test.mjs tests/comment-commands.test.mjs tests/selection.test.mjs tests/selection-surface.test.mjs tests/selection-toolbar-position.test.mjs tests/v15-comment-guide.test.mjs`47项通过。新增专项检查人工编辑准确说明全部维护禁用，EDIT／RESOLVE／DELETE／MODIFY不创建命令，真实空闲／CURRENT回读后恢复入口；原UNKNOWN、确认后读失败、同页／异页、原请求与投影边界仍通过。comment-panel.test.mjs保持原CRLF。
- 当前5173实际source map与磁盘逐一一致、运行导出存在：comments/components.tsx48928字节，panel.tsx62892，panel-owner.ts49408；CSS包含grid头部／工具宿主，不含旧工具条absolute及92px右侧补白。不是仅凭200或磁盘判正常。

隔离Chrome使用真实评论组件、编辑器及21条内存评论，在360／640／980px面板分别测3张可见卡片（含短引用、5行长引用及失效引用）：三个尺寸的最大按钮中心与引用首行中心偏差均0px；按钮均28×28，SVG水平／垂直中心偏差不大于0.5px，引用与工具不重叠，工具为static。人工编辑状态原因可见／可访问、按钮disabled及title正确，原生点击不发命令；恢复IDLE后重新可操作。普通和人工状态临时截图均已实际查看后清理。

同一预览实际点击验证编辑／取消、删除确认／取消、AI设置／取消可达；解决成功才隐藏、折叠区可重开、已展开时解决也收起，总数21不变。UNKNOWN及读到已解决后仍保留核实，原命令只准备1次／提交2次；确认后GET失败保持卡片、仅读取恢复不重复写；本页全解决的空态和第2页未解决可达，拒绝后保持可见；卸载Registry0。

## 用户实际页面

只读打开现有/requirements/2，展开助手的评论页签。实际document_work_state=MANUAL_EDITING；面板原因正确，所有可见维护按钮disabled／title准确。两张实际评论卡的引用／工具间距均8px，最大首行中心偏差均0px，工具position=static。执行原生disabled点击验证时，所有/api/非GET请求有预先拦截保护，最终实际写请求为0；未点击完成／取消人工编辑，用户会话和评论未由本轮改变。最后/requirements/1正常详情启动。浏览器Console错误0、警告0。

## 清理与未覆盖

本轮浏览器无失败；所属浏览器close退出0，临时源码／HTML／快照／两张截图／日志均清理，不留JSON或原始日志。未新增HTTP测试服务、启停用户8000／5173、改后端／资源、触发真实模型或提交推送。正常库不做评论写入，操作回执来自隔离内存；没有多浏览器／系统高对比或全业务／生产构建证据。本次未放开人工编辑期间的评论维护权限，不应把明确禁用解释为按钮会在人工编辑中发请求。

正式FE SHA256保持2039cbe1e3cf5f80c9b39f40b799cfa07ae8c3633a1c6f92d84362e7c64b9b48，BE保持8c7bad2949d4258b37296e99d06e3747bea7e209c72974168989d749cbd8220f。收尾实际核对9份文档／389条本地链接与锚点通过，AGENTS新检查规则存在，临时产物0、断点唯一；git diff --check通过，HEAD仍33a6736。独立迭代继续pending。
