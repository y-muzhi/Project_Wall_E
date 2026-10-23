# UX-023 整体视觉与交互基础检查

日期：2026-10-09，Asia/Hong_Kong。

范围：公共颜色、次级控件、工作台、导航、正文／大纲、编辑工具、辅助面板及AI输入表现；新增Ctrl／⌘+Enter发送路径。仅基础检查，不恢复完整验收或真实模型调用。

|命令／检查|结果|
|---|---|
|frontend目录：`npm run build -- --logLevel warn`|TypeScript和Vite通过；保留既有超过500kB产物提示。辅助字颜色修复及样式整理后重新构建也通过|
|frontend目录：`node --test tests/send-shortcut.test.mjs tests/guide-composer.test.mjs tests/detail-layout.test.mjs tests/navigation.test.mjs tests/focus-feedback.test.mjs tests/conversation-owner.test.mjs tests/messages-read.test.mjs`|38项通过，0失败；新增两项快捷键检查覆盖普通换行、修饰键、组合输入、229事件、重复及禁止发送状态|
|CSS指定token文字对比度|最初muted／surface-user为4.40失败；将muted加深为#62675f后六组通过，见下表。颜色修改后重新构建|
|`git diff --check`，限定本轮代码文件|通过；只有既有换行归一化提示|
|8000只读入口与`frontend/dist/index.html`比对|一致，确认服务使用最新构建|
|Playwright CLI工作台1600×1000|导航底色rgb(247,247,243)，表宽1352px，无页面横向溢出|
|Playwright CLI详情1600×1000|正文736px，面板420px；导航53px、消息区约615.77px、输入约219.23px，发送按钮底部959px小于面板底部984px。外框0px、标签无粗下划线、重复区域标题已移除，分区无重叠，无页面横向溢出|
|Playwright CLI详情1280×900|正文640px，面板396px；消息区约515.77px，输入约219.23px；发送按钮底部859px小于面板底部884px，分区无重叠，无页面横向溢出|

|文字／背景token|最终对比度|
|---|---|
|text／surface-base|15.23|
|muted／surface|5.39|
|muted／surface-user|4.97|
|accent／accent-soft|5.74|
|on-primary／primary|14.31|
|danger／surface|6.33|

浏览器前两次从临时快照未提取到AI启动按钮引用，未强行点击。随后在独立浏览器预设已定义的布局偏好（只影响该隔离会话），直接只读观察当前详情；全部非GET API请求在导航前拦截。未提交业务写请求、编辑用户正文、发送消息或调用模型。浏览器关闭，临时快照和日志目录均经绝对路径范围校验后清理，没有在项目留存测试JSON／截图／录像／原始日志。

未覆盖：键盘发送的真实DOM端到端、跨浏览器、1024px临界组合、全部编辑器浮层、长操作设置／错误提示组合和完整业务验收。指定对比度检查不等于全站WCAG验收；DOM尺寸观察也不等于所有视觉状态均已验收。
