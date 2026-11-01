# 近期代码修改与文档覆盖核对

> 2026-10-31后续：本文是归并前的覆盖检查，原日期、摘要及未覆盖不改。7份迭代最终规则现已[合入正式前端设计并归档](../../archive/merges/v1.5/合并记录-2026-10-31-近期交互归并.md)；下文“待合并”等属于10月30日现场，普通链接已重定位。

日期：2026-10-30。任务：M15-DOC-COVER-01。用户要求继续往前检查是否所有修改都有文档，不能只列最近三份文件。

范围：本次对照当前聊天的需求／更正、2026-10-29—30的7份待合并交互迭代、对应检查报告、现行计划／断点／需求映射，以及HEAD33a6736之后工作区全部19个frontend/src实现文件和6个检查文件。较早的确认按钮、人工编辑提示／入口和区块菜单已有提交，仍按现有源码及既有专项核对；H08／H10／H11沿现行索引追溯，不将本次称为整个V1.5或V1.0全部历史的重新验收。

本轮只修正文档、替代说明、索引和追踪；不改业务代码、测试输入、冻结资源、原始设计、数据库、服务或Git提交，不执行产品测试／构建／浏览器／真实调用。原报告的实际失败、时间、通过数及未覆盖内容全部保留。

## 逐组核对

| 前面需求与更正 | 实际文档及覆盖内容 | 原证据及本次结论 |
| --- | --- | --- |
| M15-CONFIRM-01 公共确认按钮 | [确认按钮迭代](../../archive/iterations/v1.5/WALL-E.公共确认按钮对齐与交互配色修正_V_1.5.md)：对称留白、BusyIndicator、主／危险／禁用配色、全部复用位置 | [原检查](confirmation-buttons-2026-10-29.md)已有；本次静态确认源码仍有10处Confirmation声明。原Python联测失败不改写 |
| M15-MANUAL-STATUS／ACTIONS／CREATE-01 | [人工编辑提示与入口](../../archive/iterations/v1.5/WALL-E.人工编辑提示居中与文案精简_V_1.5.md)：唯一居中提示、人工页隐藏文档维护、新建入口及退出恢复，三个后续要求均有记录 | [原检查](manual-editing-status-2026-10-29.md)分别记录三次检查。本次补右侧改名后来移至名称旁的接续说明，MANUAL隐藏边界仍有效 |
| M15-BLOCK-MENU-01 区块左侧菜单 | [原区块菜单](../../archive/iterations/v1.5/WALL-E.区块左侧操作菜单与悬停高亮_V_1.5.md)：沟槽／高亮、来源和评论、独立选区评论、键盘／目标及清理 | [原检查](block-menu-2026-10-30.md)已有。本次标出后续外置高亮、24×28按钮、76px沟槽及菜单120ms退出的替代关系；不继续按旧28px／点击锁定规则实施 |
| M15-EDITOR-SELECT-01 人工编辑与选区 | [选区统一](../../archive/iterations/v1.5/WALL-E.人工编辑区块与选区交互统一_V_1.5.md)：阅读／人工／历史共用高亮、原生选择时机与上方定位、六点更正为两列三行、原格式／评论边界 | [原检查](manual-selection-2026-10-30.md)含424项、隔离编辑／阅读及图标更正的独立范围。本次补菜单行为接续说明，保留原选区规则 |
| M15-SECTION-FOLD-01 正文／大纲折叠 | [标题折叠](../../archive/iterations/v1.5/WALL-E.正文标题折叠与大纲联动_V_1.5.md)：共同章节边界、唯一状态、嵌套保留、定位展开、隐藏编辑保护、评论标记、文档隔离与清理 | [原检查](section-folding-2026-10-30.md)含430项及末次19项、原浏览器未执行。本次补后续公共动画替代旧计时器，以及编辑guard、评论navigation输入及探针、outline-display接入位置 |
| M15-NAME-01 名称旁共用改名及两次反馈 | [名称编辑](../../archive/iterations/v1.5/WALL-E.名称旁改名与公共组件_V_1.5.md)：需求／文档同组件、悬停按钮、保存／取消、440px上限、常驻占位与绝对定位层、聚焦不滚动、错误／UNKNOWN恢复及原权限 | [原检查](name-editor-2026-10-30.md)分别保留首次实现、宽度与无跳动修正。本次补NameEditor输入／事件、默认值、业务适配责任及DetailFrame.titleEditor契约 |
| M15-FOLD-UX-02 对齐／菜单退出／公共动效及间距反馈 | [悬停与动效](../../archive/iterations/v1.5/WALL-E.区块操作悬停与折叠动效优化_V_1.5.md)：首行中心、中性底色、按钮间8px／距文字20px、120ms跨隙、实测尺寸180ms动画、反向／reduce／resize／销毁 | [原检查](fold-hover-motion-2026-10-30.md)分别保留438项、最终13项、最后间距6项及5173源码GET。本次补DisclosureTarget及run／finish／dispose的输入、回调与生命周期责任 |

运行页面核对也已记录在[悬停检查的同日追加](fold-hover-motion-2026-10-30.md)：5173返回本工作区源码，用户确认完整刷新后已更新。此反馈在最后加宽间距之前，不能据此宣布最新间距或全部浏览器动效验收通过。

## 当前工作区实现文件逐项覆盖

以下是本次静态审阅快照，不是新的长期状态表；能力状态仍只在需求实现映射维护。每个文件已核对差异／新增代码及对应专项，不仅检查文件是否存在。

| 实际修改／新增文件（相对项目根） | 对应记录的职责 |
| --- | --- |
| frontend/src/comments/components.tsx | SECTION-FOLD：排除折叠区块标记、订阅导航位置变化及清理 |
| frontend/src/comments/panel.tsx | EDITOR-SELECT：共用原生选区与定位；SECTION-FOLD：传入所属navigation |
| frontend/src/documents/block-highlight.ts | EDITOR-SELECT：宿主作用域外置高亮／定位，无正文属性副作用 |
| frontend/src/documents/editor-interactions.ts | EDITOR-SELECT：格式浮层复用选择观察／位置、拖选期间隐藏及销毁 |
| frontend/src/documents/editor.ts | SECTION-FOLD：原dispatch前事务guard及退役清理 |
| frontend/src/documents/navigation-view.tsx | EDITOR-SELECT／SECTION-FOLD／FOLD-UX：入口、正文／大纲状态、菜单进出、箭头及焦点 |
| frontend/src/documents/navigation.ts | EDITOR-SELECT／SECTION-FOLD／FOLD-UX：导航唯一状态、共同范围、定位展开与首行沟槽几何 |
| frontend/src/documents/outline-display.ts | SECTION-FOLD：直接复用章节范围／隐藏集合算法 |
| frontend/src/documents/section-folding.ts | SECTION-FOLD／FOLD-UX：范围、隐藏编辑保护、外置呈现及公共动画接入 |
| frontend/src/documents/selection-surface.ts | EDITOR-SELECT：原生选择观察、视口／工具栏边界和监听／RAF清理 |
| frontend/src/requirements/detail-frame.tsx | NAME：titleEditor可选插槽，避免form嵌入h1 |
| frontend/src/requirements/detail.tsx | NAME：需求名称适配器接入页头并沿原权限传参 |
| frontend/src/requirements/document-directory-view.tsx | NAME：文档名称组件、捕获目标、错误／原操作核实、创建关闭备用焦点；MANUAL原规则保留 |
| frontend/src/requirements/header.tsx | NAME：移除更多操作中的旧改名表单及强制保持弹出逻辑 |
| frontend/src/requirements/property-control.tsx | NAME：原需求保存／未知核实／详情重读适配共用名称组件 |
| frontend/src/shared/disclosure-motion.ts | FOLD-UX：公共像素轨道、连续反向、最终状态与资源清理 |
| frontend/src/shared/icon.tsx | EDITOR-SELECT：两列三行六点；NAME：现有图标体系的编辑图标 |
| frontend/src/shared/name-editor.tsx | NAME：共用显示／编辑、IME、键盘、焦点与不参与布局的编辑／反馈层 |
| frontend/src/shared/styles.css | 七组共用样式接入；本工作区增量为外置高亮清理、双按钮／沟槽、名称组件等；较早确认／人工状态样式在HEAD中保留 |

6个检查文件同样有原记录：frontend/tests/selection-surface.test.mjs归EDITOR-SELECT；frontend/tests/section-folding.test.mjs、frontend/tests/section-navigation.test.mjs及frontend/tests/browser/comments-probe.tsx归SECTION-FOLD；frontend/tests/disclosure-motion.test.mjs及frontend/tests/navigation.test.mjs的几何增量归FOLD-UX。原计时器专属断言替换、模拟边界和探针所需navigation参数均在对应检查中交代。本轮未重跑这些检查。

## 实际发现及文档修补

1. 新4份检查报告存在，但verification/v1.5/README.md遗漏链接。本次补入选区、标题折叠、名称编辑及悬停／动效入口，同时增加本核对入口。
2. 人工编辑提示文档仍写右侧改名；早期区块菜单仍写28px按钮、44px沟槽与点击展开；选区及标题折叠文档未直接说明后续菜单／动画替代。本次在原文顶部补精确接续链接及有效／被替代边界，保留原实施和失败记录。
3. 新公共名称组件、尺寸动画方法只有实现摘要，缺少集中输入／事件及默认值／清理职责。本次在各自迭代补足契约，并补编辑事务guard、评论标记生产／探针及大纲算法接入说明。
4. 设计／项目入口没有直接引导读者区分“正式设计”和“已记录但待归并的近期规则”，映射顶部仍只标H08。本次补入口并修正现行摘要、历史条目的后续接续边界；不复制新共同规格。

结论：本次范围内7组功能需求和后续更正没有发现整组未写文档；此前文档入口及替代衔接不够完整，已按上述范围补齐。代码已写入、文档有记录、正式归并、Git提交及产品验收是不同状态；本次不将后面三项自动标为完成。

## 静态检查与未执行范围

本轮实际静态结果：14份修改／新增Markdown的322个本地链接全部存在；7组迭代及对应7份原检查均已进入索引和本报告；工作区19个实现文件、6个检查文件均能在本报告逐项定位，缺失0。25文件整体内容摘要与本轮开始时相同，确认未改产品实现／检查输入。两份正式设计SHA256仍与当前断点一致，仅设计README增加导航。旧文档替代回链及公共契约已按源文件核对；git diff --check退出0。Git仅提示原pending README的CRLF后续转换为LF，无空白错误，不自动改Git配置。

未执行产品测试／类型／格式／构建／浏览器及模型；本轮只有Markdown变更，没有重新启停或探测服务。正常服务的最后观察仍引用原报告，不推断此刻进程持续存活。不触碰downloads中的用户文件、原始／冻结资料或既有业务数据。正式设计归并及Git提交仍未执行。
