# WALL-E 样式与交互自查修复 V1.5

2026-10-25。用户授权自行检查样式与交互并调整。以正式FE5.1、文档导航与框架创建、BND-WORK-SETTINGS、BND-PROGRESS为依据，在既有页面／SingleSelect／创建抽屉及composer上修复；不新增业务实体／接口或改变AI权限。

实际问题与最终规则：

1. V1.5 composer摘要丢失原设置入口结构，已有focus-visible样式未命中，原生details没有Esc取消。恢复明确“操作设置”入口、展开状态、焦点及收起箭头；Esc恢复本次展开前配置、保留最新消息，取消读取的迟到绑定不能覆盖。原请求已发送／未知后不改写；常规收起保留本地选择，发送仍为唯一提交意图。
2. 原摘要将GuideTarget.label当文档身份，章节／区块选择可能只显示范围名。现在通过实际目录显示文档名／Vn，范围另行说明，不改变阅读选择或请求目标。
3. 新建文档字段使用不同于原创建抽屉的嵌套排版。复用原字段组、显式label关联、名称1—80字符提示；非法名称阻止提交并定位字段，错误与输入关联，UNKNOWN／CONFIRMED继续核实原动作。参考文档与固定结构复选框对齐，空目录明确说明。
4. 文档导航的视图按钮缺少选中反馈，长标题与元数据／维护按钮混排。调整目录内边距、选中状态和标题／元数据／操作分行；改名聚焦并选中原名，Esc关闭返入口，中文输入组合期间不触发提交或取消。
5. 进展面板直接显示ACTIVE等内部状态及未决主题ref。改为当前有效／已被更新／存在争议及实际主题名称，原程序值与命令不变。

实现：frontend/src/guide/composer.ts、composer-view.tsx，requirements/document-directory-view.tsx、discussion-view.tsx，shared/styles.css；新增三项配置取消／迟到读取／提交后保护专项，沿用v15-ai-composer测试文件。

正式设计BND-WORK-SETTINGS补充Esc、迟到读取和目标摘要的可检查规则；见本日对应合并记录。验证详见verification/v1.5/style-interaction-review-2026-10-25.md：定向22项、完整前端358项、类型检查及临时生产构建通过；实际隔离浏览器检查通过。未改后端／冻结资源／用户数据，8000／5173继续运行，未提交推送。
