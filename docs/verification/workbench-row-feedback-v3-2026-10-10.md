# UX-025 工作台标题与行反馈基础检查

日期：2026-10-10，Asia/Hong_Kong。

范围：仅工作台标题链接及整行hover／active／focus-visible样式。CSS确认原hover标题accent蓝色加下划线，整行surface-hover #eeeeee；工作台没有持久行选中状态。

|命令／检查|实际结果|
|---|---|
|frontend目录 `npm run build -- --logLevel warn`|通过，含TypeScript及Vite构建；既有超过500kB产物提示保留，本次另有构建插件耗时提示，未阻断构建|
|Playwright CLI独立会话，8000/requirements|正常／标题悬停／按下／键盘焦点四种情况下标题色均rgb(36,36,36)，text-decoration-line均none|
|整行反馈|悬停、标题键盘焦点行底rgb(245,248,255)；鼠标按下时rgb(237,242,255)；指针和焦点移出后行底透明，恢复页面白底|
|键盘和链接|通过Shift+Tab取得实际标题focus-visible，outline为2px solid；标题仍为原a元素，href符合/requirements/数字ID格式。按下测量后在外部释放鼠标，没有导航或业务写入|
|限定本轮文件 `git diff --check`|通过，无空白错误|

浏览器拦截所有非GET API；没有编辑需求、发消息或调用模型。生产dist已更新，开发服务使用当前样式。浏览器检查正常结束，finally关闭会话，并核对临时目录绝对父路径及walle-filter前缀后清理；不留JSON、截图、录像或原始日志。

未执行完整列表导航／拖选／分页业务验收、移动触摸、跨浏览器、高对比度或真实visited状态检查。visited标题规则由CSS覆盖，浏览器隐私限制下不宣称实测已访问色；保留href不等于完整原生新标签页验收。未增加镜像CSS单元测试，本轮只做构建和有限真实样式观察。原前后端设计及模板未改，迭代V3第11节及第9.4节已同步。
