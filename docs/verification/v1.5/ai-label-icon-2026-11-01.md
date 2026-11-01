# Ai助手图标与显示名称检查

日期：2026-11-01。M15-AI-LABEL-01；HEAD33a6736上的未提交工作区。仅本轮前端展示及检查选择器修改，原其他改动与v2.0资料保持。正式设计变更与实现位置见[迭代](../../archive/iterations/v1.5/WALL-E.助手入口图标与显示名称_V_1.5.md)。

- frontend下`npm run typecheck`及`npm run format:check`：退出0，strict类型及全src格式通过。未关闭检查或引入依赖。
- 对19个包含旧页签精确名称的tools/*.mjs逐一执行`node --check`：全部通过；与HEAD归一化换行后比较，差异只有AI 对话→Ai对话。浏览器夹具显示名称同步，未执行这些旧业务脚本。
- 只读GET现有5173的requirements/detail-frame.tsx、requirements/document-records.tsx、guide/read-view.tsx、messages/timeline.tsx：均200，转换大小分别73725／29347／43545／44137字节，内联source map源码与当前磁盘逐一一致，运行导出存在；不是只检查HTTP状态。src旧精确显示名称扫描无残留。
- 独立Playwright CLI／Chrome打开`http://127.0.0.1:5173/requirements/3`：入口文字／title／aria-label均为Ai助手，SVG为1个圆与2个眼睛；点击入口后Ai对话页签1个，旧名称页签0个，页面实际启动。Console总3条，错误0、警告0。只点击布局入口，未填写／提交内容或触发AI。
- 首次临时浏览器探针因多行run-code参数报SyntaxError，改为单行后通过；首次脚本差异检查把绝对路径传入git show失败，修正为仓库相对路径后通过。两项均是检查命令问题，没有据此改业务代码。
- 两个自有浏览器会话均close退出0；快照／日志由frontend内TemporaryDirectory在finally清理，不保留JSON、截图或原始日志。没有新测试服务，正常8000／5173未启停。

正式FE新SHA256：2039cbe1e3cf5f80c9b39f40b799cfa07ae8c3633a1c6f92d84362e7c64b9b48；BE摘要保持原值。文档收尾实际核对11份Markdown／485条本地链接与锚点通过，当前断点唯一，BE摘要保持，原子临时文件与浏览器临时产物均为0；`git diff --check`通过。此次低影响图标／文案修改未另造镜像测试，未生产构建或重跑全业务／多浏览器；不能将这些静态／本地Chrome证据扩大为所有功能验收。
