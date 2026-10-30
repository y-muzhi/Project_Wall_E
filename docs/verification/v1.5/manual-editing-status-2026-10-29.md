# 人工编辑提示检查

日期：2026-10-29。M15-MANUAL-STATUS-01。修改DocumentMetadataBar及共享样式中的对应局部规则。

- `npm run typecheck`退出0。
- `node --test tests/v15-directory.test.mjs tests/v15-reading.test.mjs tests/detail-layout.test.mjs`：3个既有测试文件通过，0失败，747.65644ms。
- Chromium154.0.8037.57隔离页面加载真实DocumentMetadataBar与shared/styles.css，只注入内存中的只读owner状态；2048／1280／800／375px视口均只有1处“正在进行人工编辑”，相对元数据行中心偏移约0.008px，与左右内容无重叠、页面无横溢。长标题不产生重复提示；MANUAL→IDLE后提示移除，恢复MANUAL只显示1处；旧“正在编辑：”文案不存在。页面脚本错误0。
- 源码检索确认新提示只有一个渲染点，旧提示渲染已删除；`git diff --check`通过。

边界：本轮未再次生产构建、未运行每项业务写入链或完整产品验收；未修改业务数据、后端、模型资源或用户服务，真实API调用0。不将内存隔离owner检查称为完整编辑保存链验证。上一按钮任务的Python联测挂起不属于本次回归，本轮没有再次运行该项。

临时组件服务／浏览器在finally关闭，缓存与临时脚本已清理；不留截图、录像、JSON或原始日志。代码尚未提交或推送。

## 同日补充：人工编辑页面隐藏文档操作

M15-MANUAL-ACTIONS-01。DocumentMetadataBar新增真实文档mode订阅，MANUAL不渲染右侧文档操作组。原居中提示与保存／完成／取消保持。

- `npm run typecheck`退出0。目录／阅读2个既有测试文件通过，0失败，511.457607ms。
- Chromium154真实组件：MANUAL人工编辑时改名／确认当前版本／归档均无DOM；CURRENT且IDLE时恢复3项操作、改名可用；CURRENT且有人工会话时操作恢复但仍禁用；再回MANUAL重新移除。中间人工提示依真实activity保持1处或隐藏。页面脚本错误0。
- 初步尝试静态服务端渲染检查，因组件原useSyncExternalStore没有SSR getServerSnapshot而无法运行，未修改生产组件以适配该临时检查；改为实际浏览器挂载验证并通过。

检查页面仅使用内存owner，没有业务请求或用户数据写入。临时Vite／浏览器／缓存／脚本已清理；未执行生产构建或完整业务保存链，本轮未提交推送。

## 同日补充：人工编辑页面隐藏新建文档入口

M15-MANUAL-CREATE-01，仅改NewDocumentButton的视图订阅与条件渲染。

- `npm run typecheck`退出0；`node --test tests/v15-directory.test.mjs tests/v15-reading.test.mjs`：2文件通过、0失败，453.954268ms。
- Chromium154隔离加载真实NewDocumentButton／DocumentCreationProvider：MANUAL→CURRENT→EMPTY→MANUAL→CURRENT，两种入口DOM计数依次0／2／2／0／2；恢复后的加号实际点击打开新建文档弹窗，空表关闭正常。页面脚本错误0，未提交创建或请求业务后端。
- 临时Vite／浏览器由finally关闭，缓存／检查脚本已清理，未留测试截图、JSON、录像或原始日志；`git diff --check`通过。未重复全量验收或生产构建。

本轮继续在work修改，尚未提交推送；上轮两项已集中提交为b954017，不能用此前“尚未提交”的历史描述判断当前Git状态。
