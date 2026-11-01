# WALL-E 助手入口图标与显示名称 V1.5

日期：2026-11-01。条目M15-AI-LABEL-01，来源为用户本轮截图及两项修改要求。此迭代已合入[正式前端设计](../../../design/v1.5/WALL-E.前端设计文档_V_1.5.md#bnd-detail-需求详情)，实现与检查状态见[映射](../../../traceability/v1.5/需求实现映射_V_1.5.md)。

## 最终规则

顶部助手按钮复用消息头像的robot图标；可见文字、title悬停说明与aria-label均为“Ai助手”。对话页签、窄窗阅读视图按钮、只读对话区的可访问名称及引用该视图的帮助文字统一使用“Ai对话”。消息头像可访问名称同步为“Ai助手”。大小写与空格按此精确文本执行。

内部AI页签值、DOM关联ID、布局owner、显隐与消息挂载、调用及业务权限保持原契约；不修改历史消息或模型文本，不增加图标资源或依赖。现有浏览器夹具及19个检查脚本的旧精确名称选择器同步替换，不借此扩展旧脚本业务流程。

## 来源、实现与验证边界

正式FE／BE均为1.0／EFFECTIVE，软件V1.5。已读AGENTS强制原子写入规则、当前断点／计划／映射、FE BND-DETAIL完整布局规则及相关渲染／可访问名称；后端契约复用，本轮未重读无关AI资源。修改前FE SHA256：3e21d6273429a16f740d95e6075a93e5c215441cc4b56ad22566428c526667ef。BE仍8c7bad2949d4258b37296e99d06e3747bea7e209c72974168989d749cbd8220f。

实现位置：frontend/src/requirements/detail-frame.tsx、document-records.tsx、guide/read-view.tsx、messages/timeline.tsx及tests/browser/ai-read-probe.tsx。所有修改使用同目录临时文件、fsync、并发复核与原子替换；src先在内存按锁定Prettier配置格式化。保留原未提交改动及v2.0资料。

实际类型／格式、当前5173模块和独立浏览器结果见[检查记录](../../../verification/v1.5/ai-label-icon-2026-11-01.md)。不执行真实模型、修改业务数据、启停用户服务或提交推送，不将本次显示检查扩大为业务全量验收。
