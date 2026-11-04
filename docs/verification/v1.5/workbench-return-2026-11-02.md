# 工作台返回位置恢复检查

历史局部检查：用户后续反馈仍退出应用，最终已将按钮改为直接导航；以下21项及来源恢复方案不作为当前按钮最终验收。见[后续修正与23项／真实前序边界检查](workbench-return-direct-2026-11-02.md)。

日期：2026-11-02（Asia/Hong_Kong）。HEAD 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0、master；原工作区文档与前轮固定当前文档改动保留。本轮源码仅frontend/src/application/router.ts及既有application-router.test.mjs；依据[M15-RETURN-01](../../iterations/pending/v1.5/WALL-E.工作台返回位置恢复修正_V_1.5.md)，未合入正式设计、未提交推送。

## 原因及修正

普通工作台进入需求1再点击“工作台”原本可返回。离线按真实ApplicationRouter／DetailDeparture复现：刷新前来源历史仍在，辅助sessionStorage位置缺失／不可读／被清空或过期，constructor忽略已校验DetailEntry.position而误取0，返回成为history.go(0)，departure已到LEAVING，后续点击无法再发起离开。新回归在原代码上6项既有通过、5项新增失败；这是特定条件的程序复现，未取得用户原标签页内部状态，不能宣称用户现场唯一原因已证实。

修正使用原decodeDetail完整校验后读取自身position，并从from登记原工作台位置；批准返回核对path与真实entry_id，恢复原查询／页码／滚动。人工草稿保存／失败警告、主导航和直接进入默认工作台的既有规则保持；没有API／数据／按钮样式改动。

## 离线与静态

- `node --test frontend/tests/application-router.test.mjs frontend/tests/departure.test.mjs frontend/tests/workbench-history.test.mjs`：21项通过。覆盖四类存储异常刷新后原工作台恢复、查询／滚动及后续导航、浏览器返回保存失败继续编辑／明确离开、原创建保护、直接详情与错误路由等。
- frontend下`npm run typecheck`、`npm run format:check`均退出0；`git diff --check`通过。源码与测试均完整内容→同目录临时文件→flush／fsync／关闭→原文件并发核对→os.replace，保留编码、换行与权限，不直接运行写回格式化。
- 首次修正后返回已可达，但4项测试的查询预期失败；定位为新夹具只saveEntry没有提交workbench.query，进入详情时原生产流程正确保存真实查询，覆盖了伪设快照。修正夹具为实际查询及滚动后21项通过，没有修改生产查询语义。
- FE／BE正式设计摘要保持b294153e11ef764f36f92b7390dc817c6ed079a81734c770ebe6f217601e2920／36d2e28630b5099a30253e5a5881492c8fc50c3cffaf4d9d4a88341bdc24defd。

## 现有服务与浏览器

Python urllib只读5173的/src/application/router.ts：实际ApplicationRouter导出有效、响应38560字节、source map的sourcesContent与磁盘相同，已含本轮恢复位置逻辑；源码SHA256为27a715ce2b6a54855ae93a4d9a2ef3db48e79f132d6e305fa4b4bca2985106df。无空模块，不需要刷新文件时间戳或重启服务。未枚举PID；5173／其现有API可只读访问，未启停用户服务或重建8000静态dist。

使用已缓存Playwright CLI、自有walle-nav-20261102会话：

- 正常工作台进入既有需求1，点击截图对应工作台入口，实际回到/requirements。
- 独立浏览器内搜索11111、进入详情并打开进展；分别仅清除返回位置辅助键／把辅助位置设为过期0，刷新详情，再点工作台：均回工作台并保留11111查询。
- 清除辅助位置后刷新详情，浏览器Back回到工作台。
- 自有新标签页通过初始化脚本让sessionStorage getter抛错，工作台进入详情、刷新再返回：实际/requirements、Console错误0、非GET0，标签页finally关闭。
- 全程拦截非GET业务请求；普通页面与其余回归Console仅React开发提示，无错误。第一组脚本所有断言完成、CLI退出0；其console.log不在CLI返回展示，结果按断言完成及原Console核对记录，不伪造额外输出。后组使用结构化return，明确结果passed／0／0。

初始npx --no-install尝试因沙箱内npm DNS不可用失败，改用本机已缓存CLI，无下载安装。沙箱直接本机HTTP与CIM访问被环境限制，已按授权使用本机只读模块访问；没有通过这些失败推断产品异常。只读查看原Chrome的CUA调用因工具不能可靠识别当前网址而终止，未继续操作该窗口；已知5173地址的独立会话检查不代表直接修复了用户原标签页内存。

## 边界与清理

未执行全量测试／生产构建／后端专项或真实模型／计数；本轮无对应后端／资源变化。人工编辑草稿实际写入与多浏览器组合未新增实测，离开保护由相关离线覆盖。截图进展区读取失败提示未作为本轮独立问题定位，不用返回修复宣称其原因已解决。

自有浏览器会话已close；临时脚本、当次四份快照／Console原始文件按精确路径清理；历史其他会话产物不触碰。cleanup-test-artifacts.py --dry-run为JSON0／screenshots0。只留本Markdown证据；无自有服务进程，正常库／正文／密钥／审计保持。
