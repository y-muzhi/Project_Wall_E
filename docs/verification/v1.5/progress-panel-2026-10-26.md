# 大纲与进展独立面板专项检查

2026-10-26，M15-PROGRESS-02。用户拒绝进展内容上下堆在对话区。本轮改前端布局／读取生命周期、既有Probe和偏好专项、V1.5责任文档；不改后端业务或模型资源、不操作用户业务记录、不启停用户原服务、不执行Git写操作。

## 实现与离线检查

DetailLayout新增PROGRESS合法页签；DetailFrame按AI／进展／评论／文档记录排列，全部内容保持挂载；detail将进展移至独立槽。DiscussionProgress移除顶层details，独立满高滚动、固定标题／阶段／返回对话；嵌套主线与主题、来源和原C06设置保留。完整讨论仅实际可见进展时读取；readPanel不将PROGRESS误分派为版本记录。返回对话等待实际输入可用后聚焦，普通tab切换保留键盘焦点规则。

新增1项现有布局专项，验证PROGRESS偏好存取、单视图／关闭重开及原宽度保留；未为样式逐行造测试。frontend执行：

- `node --test tests/detail-layout.test.mjs tests/v15-discussion.test.mjs tests/v15-discussion-presentation.test.mjs tests/motion.test.mjs`：25 passed／2623.7329ms。
- 最终`npm.cmd run typecheck`退出0。
- 最终`npm.cmd test`：374 passed、0 failed／4267.6759ms。
- `node node_modules/vite/bin/vite.js build --outDir <本轮临时根>/frontend --emptyOutDir --logLevel warn`最终退出0，仅既有chunk体积提醒；frontend/dist未覆盖。

## 实际浏览器检查

Playwright技能／CLI、Chrome155，Windows、100%缩放。tools/serve-v15-offline.py独立临时SQLite／HTTP／Worker、私有Counter／Gateway；PID36004／端口54009／PTY17658，named browser walle-progresspane-20261026。经正常UI创建隔离需求，1次私有[progress-layout]讨论生成4主题／6主线和长标题，2次SET_FOCUS走原程序命令，不发送额外Chat。

| 路径 | 实际结果 |
| --- | --- |
| 对话区与独立高度 | AI内discussion-progress节点0；AI内容区853px、消息阅读586px。进展切入后内容区853px，内部实际852px、内容1249px，独立scrollTop100；固定标题top130等于进展区top130，不再上下分割消息区 |
| 切回保留 | 同一输入DOM，文字“保留的未发送输入”保留，消息scrollTop80→80；返回对话在实际输入可用后聚焦成功 |
| 读取边界 | AI初次进入完整expand GET0；首次进展展开GET1；稳定内层折叠expand GET0；切AI后重新读取详情expand GET0。普通详情／运行只读请求不冒充真实模型调用 |
| 主题选择 | 等待成功Toast后，当前重点为实际新主题，焦点为当前重点，scrollTop0；原PATCH与GET核实，无额外Chat |
| 360px辅助面板 | 外宽360px／内宽358px，四入口均可见、页头scrollWidth358等于clientWidth358，进展无横向溢出 |
| 视口 | 1920×1000、1280×600、1100×800、1024×800；进展高度分别852／452／660／660px，接近各自内容区全高；整页与页签栏无横向溢出 |
| 键盘／偏好／reduce | ArrowRight切评论、Home切AI、再ArrowRight切进展；reduce运行动画0；刷新后PROGRESS偏好恢复，实际主题可读 |
| 视觉与控制台 | 临时截图复核独立页签、标题、重点与主线层级，无上下消息挤占；最终console Errors0／Warnings0 |

首轮实际发现进展根未受内容区高度约束（根1249px／父853px），已补独立flex容器与overflow后最终复核852px；返回输入过早聚焦时未成功，改为实际可用后聚焦并最终通过。第一次CLI多行参数解析失败未执行动作，改为临时文件；一次旧快照ref失效重新snapshot继续，没有重复业务提交。首轮主题焦点及内层读取在命令核实未结束时采样，最终按成功Toast及稳定现场复核，不将过早采样写为产品通过证据。

## 边界与清理

UNKNOWN／CONFIRMED及取消只读、原命令重用由原owner专项覆盖，本轮未另跑断网／多标签浏览器组合；高倍缩放、其他浏览器及全部业务组合未重新验收。整版人工语义仍待原人工入口，不因为UI改造升级状态。

named browser已close；PTY17658发送stop后原36004／54009退出0，实际私有count_batches=1／chat=1，真实供应方调用0；临时根walle-v15-browser-iykv44b6（含构建／脚本／快照／截图／隔离库）由工具自动清理。用户服务8000／5173保留；当前源码由5173 Vite提供。最终服务与项目临时产物检查见下方收尾记录。

收尾：16份责任文档283个本地链接无缺失；git diff --check最终退出0（现有源码CRLF提示不构成错误），本轮文档已按既有LF字节规范保存。cleanup-test-artifacts.py --dry-run为JSON0／截图0，隔离根不存在、54009无监听；用户8000／15852与5173／12440保持，页面／后端API／代理及当前frame源码GET均200，源码含PROGRESS。没有清理旧拒绝删除的目录、正常业务库或审计。
