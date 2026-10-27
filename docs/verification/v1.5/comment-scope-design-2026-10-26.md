# 评论处理范围分离设计静态核对

2026-10-26，M15-COMMENT-SCOPE-01。用户提出独立设置评论允许操作范围、类似对话区。本轮只Markdown／相关源码静态阅读，不修改代码／正式设计／资源、用户库／服务或Git，不运行产品测试／类型／构建／浏览器／HTTP／真实模型或计数。

已读当前AGENTS流程／文档规则、断点及映射、正式FE评论入口与操作设置、BE C05／I34及范围／版本／幂等规则，comments commands／panel-owner、guide/scope／composer-view及WalleApi。当前评论请求仅两个版本，范围由评论锚点导出；对话已有DOCUMENT／SECTION／BLOCK／SELECTION与真实目标。草案选择复用，不把拟增scope_mode说成现有能力。

[专项](../../archive/iterations/v1.5/WALL-E.评论定位与AI处理范围分离专项_V_1.5.md)0.1 DRAFT留pending；用户提出分离方向，默认原范围、卡片内展开及参数枚举为推荐细化，未冒充已批准完整技术方案。没有删除或放宽选区外保护，没有给原run16补建批次或改写模型返回；无产品验收结果。

13个相关源／正式文件按路径UTF-8与文件SHA256二进制顺序聚合，基线2be9d90e61610b1d802af68b3f94e4bf898a151d75bcb8a966324b0033eeac9a；正式FE ccedbe7f…／BE5bbd4728…保持，旧M15-COMMENT-01改动不受本轮影响。收尾链接／差异及摘要核对结果补于下。


最终静态结果：9份责任Markdown的182个本地链接有效；13个相关源码／正式设计文件聚合仍2be9d90e61610b1d802af68b3f94e4bf898a151d75bcb8a966324b0033eeac9a，原修复代码与正式FE／BE未变。git diff --check退出0，仅既有comments/panel.tsx换行规范提示。无新产品检查／构建／浏览器／HTTP／真实API或服务／Git写操作；草案仍DRAFT、待实现，不能按计划提前记通过。
