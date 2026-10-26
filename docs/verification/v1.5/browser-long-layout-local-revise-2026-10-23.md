# 长正文布局与局部修订浏览器检查

2026-10-23；Chrome独立headless／Playwright CLI 0.1.22，临时生产前端及真实FastAPI／SQLite／Worker。私有离线Counter／Gateway，真实API为0。准备数据通过实际HTTP接受长稿GENERATE及长输入DISCUSS，原生浏览器补输入／滚轮／缩放／抽屉键盘与局部REVISE；不把全部准备过程说成UI。

长稿有41行表格（含标题）、80段补充正文，共87区块；长USER输入构成实际对话滚动内容。1024／1280／1440／1920×900px下documentElement.scrollWidth分别等于1024／1280／1440／1920，未溢出整页。表格实际宽608／608／744／1024px，正文scrollHeight9934／9934／8814／7694，对话scrollHeight8268／7130／6463／6463；各自容器高度有界。

1440px原生滚轮：初始正文0／对话6021；在正文滚动800后正文800／对话6021；在对话上滚500后正文800／对话5521；window.scrollY始终0。未发送输入“Keep this unsent draft”保留；收窄1024仍保留，打开导航抽屉再按Escape后焦点返回“展开文档导航”，页面无溢出。

原生点击第一段正文，操作设置选修订并保存、采用当前阅读文档、当前区块，再明确发送；run3实际COMPLETED／APPLIED，V1→V2。只读SQLite对比原CONTENT与新CONTENT：从范围章节起至文末逐字节一致（含表格／80段），全部87区块稳定ID保留，确认未改范围外。不是只观察视觉文本。最终console Errors=0、Warnings=0。

清理：浏览器v15-layout close；临时服务PID63776／port59184／会话37413正常stop退出；离线count3／Chat3，临时目录hlc0oozc自动清理，未改用户服务或库。没有截图／录像／原始日志或JSON报告留存。测试所需临时浏览器输出已随目录删除。

本记录证明本次布局／输入／滚动组合和BLOCK修订；不扩展为所有焦点／表格编辑／双标签断网组合或真实模型效果验收。
