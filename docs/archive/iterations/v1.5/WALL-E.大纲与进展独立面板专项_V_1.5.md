# WALL-E 大纲与进展独立面板专项 V1.5

2026-10-26，M15-PROGRESS-02，已实现并合入正式FE。用户指出纵向展开占据对话区、内容拥挤，明确不再在对话区上下增加内容展示。

最终规则：移除AI对话内部的进展折叠区；新增与AI对话、评论、文档记录并列的“进展”页签，面板标题“大纲与进展”。完整使用辅助面板高度，可独立滚动与调宽，保留原当前重点／下一步、主线主题、依据、来源、设置与原程序命令。“返回对话”切回原消息输入，组件保持挂载，保留输入与阅读位置。窄面板入口使用短标签，完整标题由面板和提示提供；键盘沿已有tablist方向键／Home／End。

完整discussion仅进展页签实际可见时按实际版本读取；切出立即取消所属观察读，不取消已接受程序命令或运行。未打开无完整读取，内部折叠不触发顶层请求。浏览器偏好right_tab增加PROGRESS，既有三值仍有效，沿原schema_version=1及键名，无新业务契约或实体。原M15-PROGRESS-01信息层级保留，其对话内折叠容器被本专项替代。

已按职责合入正式FE5.2／BND-PROGRESS／INF-BROWSER及8.4，当前SHA256=dd6f03f0464ac03f0147c8b8d6227d6de5e2837f47a3eb0702ae16b2a97a8266。定向25项、最终374项／类型／临时生产构建通过；实际隔离浏览器验证独立满高、同一输入与scroll80保留、360px入口、键盘／reduce／偏好及读取边界。证据见[专项检查](../../../verification/v1.5/progress-panel-2026-10-26.md)。后端与模型资源不变，不扩大人工语义验收或真实调用权限。

实现位置：detail-layout／detail-frame／detail／discussion-view／discussion-progress.css、detail-owner原readPanel，以及既有browser Probe与detail-layout专项。临时浏览器／服务／产物已清理，私有计数1／Chat1，真实供应方0。首次高度约束与返回焦点问题修复，未覆盖边界见证据。
