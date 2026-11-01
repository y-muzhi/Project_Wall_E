# 开发服务空模块导致启动停留修复

> 同日后续：已完成[根因机制隔离复现](dev-module-race-analysis-2026-11-01.md)，正式5次均复现“完整保存后缓存仍空”。下文“内部时序未复现”保留恢复阶段事实；原事故的逐次文件事件仍没有追踪证据，不等于已完成代码级防复发保护。

日期：2026-11-01（Asia/Hong_Kong）。M15-DEV-START-01。用户反馈一直停在“正在加载WALL-E…”，完整刷新仍无效。HEAD33a6736及全部原未提交改动保留。本轮修复现有开发服务运行状态，未改产品源码内容、接口、正式FE／BE、数据或资源，未重启前后端、发起模型调用或提交推送。

## 已证实原因及恢复

5173正常监听PID14996，8000正常监听PID10452，入口、主要模块及API代理GET可返回200。旧React优化依赖URL的504属于过期请求，当前main实际导入的依赖均200，不能以旧URL断定浏览器缓存为本次根因。

关键异常是**开发服务返回了空源码转换缓存**。index.html的占位要等main.tsx及其静态依赖成功加载后才能替换；空模块没有要求的命名导出，模块链接阶段就失败，尚未进入main里的start().catch，因此页面一直保留加载占位。

| 模块 | 磁盘现场 | 5173修复前返回 | 实际处理及证据 |
| --- | --- | --- | --- |
| requirements/detail.tsx | 17440字节，含RequirementDetail导出 | 167字节，仅sourceMappingURL；sourcesContent为单个空字符串，无要求的导出 | 仅刷新文件时间戳，Vite重新转换；返回59391字节，RequirementDetail恢复，文件内容摘要不变 |
| comments/components.tsx | 9952字节，含CommentList等导出 | 171字节，空sourceMappingURL结果 | 浏览器Console明确报CommentList未导出；仅刷新时间戳后重新转换，浏览器启动恢复，内容摘要不变 |

使用Python的os.utime更新这两个已确认异常文件的时间戳，前后SHA256分别保持：detail为2a7e9e4dbb8bc158698524aa050fc35e1839e75aa2c17a3655bcad1c5991651c，comments为3ccf43840fd26f5b07354a3e18472297e708c74f014c9d42a410556b38709526。没有删除依赖缓存、安装依赖或重启服务。缓存何时读入空内容的内部时序未复现，不将“可能读到整文件写入窗口”记为已证明的唯一成因；AGENTS增加原子保存和实际转换结果检查，降低再次出现同类空转换的机会。

## 实际检查

- 通过沙箱外只读Invoke-WebRequest和宿主文件读取比较响应内容／源码，保留上表摘要，不留原始响应。
- Python ThreadPoolExecutor＋urllib对全部145个src的TS／TSX模块核对source map与非空磁盘源码。先定位详情空模块并修复，首轮全量扫描仅剩评论空模块；修复后末次145个均无该异常，读取错误0。
- 第一次独立Playwright工作台等待20秒失败。随后使用snapshot／console／只读run-code，实际看到CommentList未导出的错误；这次失败不改为通过。
- 修复两处后使用现有Playwright CLI wrapper、安装的Chrome和独立临时会话：`open /requirements → snapshot → 等待.workbench`，结果phase=READY、启动占位0、Console错误0／警告0；`goto /requirements/3 → snapshot → 等待.detail-product`，结果详情可见、启动占位0、Console错误0／警告0，文档导航与工作区均显示业务空态“暂无文档”。只打开页面，没有业务点击、用户正文改动或AI请求。
- 三次所属浏览器会话均在finally调用close，退出0；快照／日志均在frontend内TemporaryDirectory，成功、失败均清理，最后临时入口0。没有借用或关闭用户原Chrome窗口，没有JSON报告、截图或原始日志留存。
- git diff --check通过；仅源码时间戳变化，两个源码内容摘要不变。本轮无需重跑类型／格式／构建及业务测试，旧检查成绩不作为本轮新结果。

本轮证明当前运行服务的入口、145个模块及工作台／需求3启动恢复。未执行创建、编辑、评论保存、真实模型或多浏览器验收，原专项缺口保持。正常服务进程归属沿上述观察，后续不凭旧PID推断仍存活。
