# V2.2 只读资料资源装配与 Windows 专项

日期 2026-11-26（香港时间）。开发和集成分别在 `codex/2.2` 与 `codex/2.2-integration`，读取 V2.01 后端 4.12.2、4.22.2 和恢复启动断点。源文件经同目录原子替换。新代码复用相同 v1/v3/v6/v7 模板清单、路径、长度、SHA、标题继承及 CollaborationResources 内容引用。恢复入口继续保持完整固定程序验证，普通入口仍使用完整 ResourceCatalog。没有新的业务路由或数据库格式。

两工作区分别使用自己的 npm 依赖执行 `npm run build -- --outDir <试验根>`，TypeScript 与 Vite 均通过，旧分块体积提示保留。R527 两侧分别用各自 Win Python 执行资源、版本资源和新恢复资料专项，均 13 passed、4 deselected、47 subtests passed。新测试比较五种固定历史模板及消息契约，拒绝错误 digest、错误模板用途和模板同尺寸篡改。恢复资料对象初始化未运行普通 Function 的 JSON Schema 元结构校验。R526 真实固定恢复另验。

R528 分别用固定 Linux 解释器运行两个工作区各自的 25 个 V2.2 专项文件。每侧 315 passed、2 skipped、1 warning，均退出 0。R530 在两套 Windows 解释器分别构造完整目录，模板、Function、活动版本的组合摘要均为 `f6170e042364650ce7db6bf4c7b6bf6ca7ca0e82f09a4aa6d42b7f20f5948b32`，与 R521 一致。开发侧完整目录 2.791 秒、资料模板 0.150 秒、协作目录 0.356 秒。集成侧分别 2.685、0.147、0.363 秒。两套读目录分别与完整目录模板结果和发布摘要一致。Windows 耗时不代替 Linux 固定启动。

## R548 历史协作资料资源的离线复核

使用两个工作区各自项目锁定的 Python，实际从磁盘读取 v15、v16、v17、v18 四份历史协作发布及契约。以已有 `discussion_resources()` 装入 `DocumentResources`，调用 `for_collaboration_release` 逐版对照原完整 `ResourceCatalog`。两边均取得相同契约内容和发布引用。选择 LONG 得到原 v18，返回默认 profile 后仍复用原验证对象；错误发布引用拒绝。此项为真实冻结资源的离线选择和校验，没有启动服务或连接供应方。
