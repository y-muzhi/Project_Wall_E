# 新建文档入口位置检查

2026-10-25，用户明确要求调整入口位置。日常创建从文档／大纲切换与列表之间移到“文档导航”标题行右侧32px＋按钮，保留中文可访问名称与title；零文档起步保留手动创建文字入口，创建后只剩日常入口。DetailFrame接收outlineActions，复用原NewDocumentButton／抽屉、权限及接口，未另建创建流程。

命令：frontend目录`npm.cmd run typecheck`退出0；`node --test tests/detail-layout.test.mjs`7 passed／94.31ms；最终临时生产构建退出0（只有既有大chunk提醒），未覆盖frontend/dist。未为可逆位置／样式另造测试，不重复此前361项全量。

Playwright技能／CLI、独立Chrome及tools/serve-v15-offline.py：真实UI创建隔离需求，1600px导航标题行＋按钮实际32×32、x372／y88，旧列表按钮不存在；点击／Esc返回＋，收起再展开仍可创建，实际创建“通过顶部入口创建”后日常入口1个、空白页入口0个。少量视觉截图仅在临时目录查看。

首次1100抽屉检查发现React portal的Esc被导航提前拦截，结果弹窗仍开、导航已收起。修复DetailFrame按activeModal／defaultPrevented／isComposing让内层先处理，最终类型／构建及实际UI复验：第一次Esc弹窗0／导航仍展开／焦点“新建文档”，第二次Esc才收起导航并返展开入口；1024px再次打开／关闭创建，焦点回＋、scrollWidth=1024。最终console Errors=0／Warnings=0。

清理：只关闭浏览器walle-newdoc-20261025，PTY20301发送stop，隔离PID70864／64013退出0，Counter／Gateway均0，TemporaryDirectory输出清理完成。测试数据／CLI快照／截图／临时构建随walle-v15-browser-qamu4xkt删除；用户8000／29692、5173／57236保持运行，用户库、后端、模型资源和Git未操作。未新增真实API，不把本次布局检查当模型语义验收。
