# 主导航固定图标与悬停提示检查

日期：2026-11-02（Asia/Hong_Kong）。HEAD 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，master；原工作区前轮代码／文档及V2.0资料保留。本轮依据[M15-NAV-RAIL-01](../../iterations/pending/v1.5/WALL-E.主导航固定图标与悬停提示_V_1.5.md)，仅修改application/navigation.tsx、shared/styles.css和shared/motion.css；正式设计未合并，未提交推送。

## 实现与必要检查

固定64px应用图标栏及同宽品牌区，W静态显示；入口只显示原工作台图标，中文可访问名称和aria-current保持。鼠标悬停或键盘focus-visible在右侧显示黑底白字提示，移出隐藏，Esc关闭后聚焦保持；浮层命中桥允许跨过8px间隙并悬停在文字上。点击沿router.mainNavigation及原DetailDeparture保存保护。删除展开／收起、窄窗主导航抽屉、开合偏好读写和快捷键、专属旧CSS／动效；详情自己的文档目录和保存保护保留。

- `node --test frontend/tests/application-router.test.mjs frontend/tests/departure.test.mjs frontend/tests/workbench-history.test.mjs frontend/tests/detail-layout.test.mjs frontend/tests/focus-feedback.test.mjs frontend/tests/motion.test.mjs`：43项通过，涵盖原路由、草稿保护、实际可用宽度／窄窗、焦点及共享动效。不为可逆样式另建逐行对应测试。
- frontend下`npm run typecheck`、`npm run format:check`均退出0。三份源码用同目录临时文件→flush／fsync／关闭→权限保留／原文件并发核对→os.replace；没有对原源码直接覆盖或写回格式化。
- frontend/src全文无主导航collapsed偏好、展开按钮／抽屉／旧标签专属类残留；共用modal、motion与文档目录仍有实际依赖，未删除公共机制。

## 服务现场与隔离浏览器

初次尝试现有5173的页面与模块均连接拒绝；随后只读端口确认5173未监听、8000在监听、5186空闲。没有把前轮5173可用状态当作本轮事实，也没有重启用户服务。启动本轮自有5186临时Vite，代理既有8000；使用已缓存CLI会话walle-nav-rail-20261102检查，业务API仅GET。结束已close浏览器并Ctrl+C停止本轮Vite（exec session76613）；8000用户服务未启停、静态dist未构建／更新。

5186实际模块检查：navigation.tsx有效ApplicationNavigation导出与source map正文等于磁盘，styles.css?direct及motion.css?direct亦一致。SHA256分别为b5ff0cb30772d631269d62a8345e040f9b3209b5f2a9fea9059898c3165c6cc5／b22fdd6b8ebd9bc40c1166bd06cd3d9eb0070c7c9ea4f26cd8f54a819bd525f9／550fd3db3591db283c7330497e998d5b969869932362abd30c6c98cbd95e85b9。无空模块或额外时间戳恢复。

实际工作台／需求1页面检查：

- 静止提示隐藏；悬停显示黑色“需求工作台”，跨隙及悬停提示本身保持，移出隐藏。悬停前后完整布局测量一致，提示交互导致API GET增量0。
- Tab聚焦显示提示；Esc隐藏且焦点仍在按钮；移出再聚焦恢复。没有第二个原生title提示。
- 空的新建需求模态焦点循环保持、Esc取消；没有创建任何正常业务数据，也没有用主导航抢占模态。
- 1920／1024／360×1000宽度下：图标栏64px、主区起点64px、实际按钮47×40px（64px栏扣两侧内距及1px边框）、图标22×22px；页面横向越界均false。两种旧开合偏好都不影响固定栏，没有旧开合按钮。
- 需求1所属aria-current=location保持；悬停后点击图标实际回到/requirements工作台，走原保存保护入口。截图局部已临时目视核对，符合参考图的图标＋黑色文字提示；不是静态组件示例。
- Console错误0、非GET0，无模型／计数请求，无正文／状态／卡片／评论写入。

首次浏览器脚本的自动审批接口返回403，命令未执行；核对脚本确为隔离会话／仅GET后重试同一受审请求成功，没有绕过审批。首次5173连接失败与此次工具故障均不记为产品验收通过。

## 边界与清理

未执行全量测试／构建／后端或真实供应方。当前导航没有业务禁用／处理中状态，保存／创建互斥仍由原owner与模态处理；真实人工编辑保存、未知请求、多浏览器及所有空／错业务组合未新增视觉验收，所列相关专项保护保持。触摸设备无悬停时可直接点击中文可访问图标，未新增真机触摸／读屏验证。

本轮独立迭代继续pending；正式FE／BE摘要保持b294153e11ef764f36f92b7390dc817c6ed079a81734c770ebe6f217601e2920／36d2e28630b5099a30253e5a5881492c8fc50c3cffaf4d9d4a88341bdc24defd。专属临时目录内脚本、局部截图、快照和Console在核对绝对路径后清理，仅保留本Markdown。5173当前未运行，8000静态页面尚未加载本轮改动；本轮完成的是源码及隔离页面验证，不宣称已更新正常用户服务。
