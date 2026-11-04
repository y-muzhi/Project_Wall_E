# 工作台按钮直接导航检查

日期：2026-11-02（Asia/Hong_Kong）。HEAD 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，master；本轮在前轮未提交router／tests及文档基础上修正，其他工作区改动保留。依据[M15-RETURN-01后续最终规则](../../iterations/pending/v1.5/WALL-E.工作台返回位置恢复修正_V_1.5.md)。正式设计未合并，未提交推送。

## 用户纠正及最终实现

用户反馈返回按钮退出应用回到浏览器主页，明确应直接返回前端工作台列表。前轮仍按持久位置差值history.go，格式校验和popstate目标核对不能证明浏览器实际前序页面；跨文档后退可能先卸载应用而根本不进入原页popstate。前轮缺少真实历史与保存来源不对应的检查，原21项通过不代表这个边界已解决。

本轮backToWorkbench删除来源步数／history.go分支，保存保护成功后只replaceState(null,'','/requirements')，随后apply('/requirements',false)。进入默认列表／第一页／顶部，不恢复来源筛选。去掉仅供原按钮读取的detailEntry成员，apply内改局部变量；既有历史校验仍用于原生浏览器Back，保持其原查询恢复，不新增另一套路由。人工保存失败继续原警告，取消仍在详情，明确离开才进列表。

## 实际检查

- 更新专项预期并补“来源记录合法但实际前页是主页、按钮不得遍历history”和“直接返回仍等待保存及失败警告”边界；修正前application-router为6通过／7失败，其中新增历史遍历禁止明确失败，另6项为默认列表新规则与旧行为差异。
- `node --test frontend/tests/application-router.test.mjs frontend/tests/departure.test.mjs frontend/tests/workbench-history.test.mjs`：修正后23项通过，含四类存储异常、默认列表、原生Back草稿保护及原创建保护。
- frontend下`npm run typecheck`、`npm run format:check`均退出0，源码整文件使用同目录临时文件fsync／关闭／并发核对／os.replace。无写回格式化、无后端及资源变更。
- Python urllib只读5173实际router模块：ApplicationRouter导出有效、source map正文与磁盘一致、backToWorkbench含replaceState且无history.go；源码SHA256为36ae09516d9cc4e8b5a302b7f68190c7cc7df1a058569ca36e720657709a9325，未触发空模块修复或服务重启。

独立Playwright会话walle-direct-return-20261102，正常5173及现有API只读，拦截所有非GET：

1. 正常工作台搜索11111→需求1→返回：实际/requirements默认列表、搜索框清空，history.length保持，未增加详情往返记录。
2. 自有标签先进入data本地主页夹具，再打开需求1；注入前轮真实保存的合法详情来源记录，刷新后返回：仍为同一文档内/requirements工作台，预设document token保持，未跳出应用。
3. 直接打开/requirements/1后返回：实际工作台列表。Console错误0、非GET0，均有实际标题与URL断言，不通过模型或业务写入造数据。

首个浏览器探针用framenavigated次数判断离开，因Playwright对同页replaceState同样发出该事件而误报unexpected browser traversal；当时已显示工作台。改为实际文档token＋URL＋工作台标题核对，复查三场景均通过；没有因此修改生产代码。原标签页未接入，不声称直接读取其内存状态；真实浏览器边界由自有标签复现。

## 边界、服务与清理

未执行全量／构建／后端／真实模型或计数；实际人工草稿写入和多浏览器组合未新增视觉检查，保留专项保存失败／取消证据。无业务数据写入或服务启停，8000静态dist未重建；正常启动仍tools/ai-service.py --start --credential-file .env.local及frontend下npm run dev，本轮未执行。自有浏览器已close，无自有服务；临时脚本／快照／Console在已校验的本轮专属临时目录清理，只留本Markdown。前轮报告保留历史并顶部指向本次最终规则。
