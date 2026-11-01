# 名称旁公共改名检查

日期：2026-10-30。M15-NAME-01。代码状态：HEAD33a6736加已有区块／选区／折叠及本轮名称编辑修改，原未提交改动保留；未提交或推送。正式FE／BE1.0／EFFECTIVE不变，来源摘要见[专项](../../archive/iterations/v1.5/WALL-E.名称旁改名与公共组件_V_1.5.md)。

实现：新增shared/name-editor.tsx，DocumentMetadataBar及页头RequirementPropertyControl共用名称、悬停／焦点按钮、输入、保存／取消、组合输入保护和焦点恢复。旧信息栏改名按钮／document-rename-form及更多操作内属性表单已删除，清理对应CSS。DetailFrame增加titleEditor插槽，表单不嵌在h1内；文档创建返回焦点定位同步新结构。原属性／目录命令不变，原目标、metadata_version、名称码点上限和UNKNOWN／CONFIRMED恢复继续由原命令处理。

环境：Windows PowerShell，Node24.15.0、锁定前端依赖、TypeScript strict及未使用检查；离线专项与构建加载tools/quality_node.cjs禁止真实网络连接。未启停用户服务，不写用户名称／正文或数据库，不调用模型／计数API。

执行结果（工作目录frontend）：

- `npm run typecheck`：退出0。
- `npm run format:check`：退出0，全部src符合锁定Prettier配置；此前仅对本轮触及文件运行Prettier写入，保留已有修改。
- `node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/property-edit.test.mjs tests/header-commands.test.mjs tests/v15-directory.test.mjs`：13通过、0失败，1865.6853ms。覆盖需求名称20码点及非法输入、原请求未知恢复、元数据冲突与未发送文本保留、独立命令恢复、目录目标／版本绑定、确认后只重读及不抢阅读选择等原程序边界；不是新表单的浏览器交互证据。
- Python TemporaryDirectory内执行`node --require ../tools/quality_node.cjs node_modules/vite/bin/vite.js build --outDir <frontend内随机临时目录>`：1266模块、2.20秒、退出0；只有既有大chunk提示，无构建失败。受控目标先核对位于frontend内，成功／异常均由上下文清理；清理确认True，未覆盖frontend/dist。
- `git diff --check`：退出0。只读引用核对确认生产页面两处接入同一NameEditor，旧入口／专用样式已移除；正式设计及原命令文件未修改。

失败及修复：本轮上述检查无失败。未运行全量前端／后端、浏览器、真实IME、多浏览器或真实供应方验证；悬停显隐、输入焦点、长名称／窄窗及实际保存交互没有本轮浏览器证据。历史浏览器专项不当作本轮重跑，正式设计归并仍待后续文档收口。

清理：只保留本Markdown汇总；无测试JSON、截图、录像或原始日志，无本轮测试服务遗留。

## 同日追加：名称输入长度反馈

用户新截图显示两个输入框都撑满容器，保存／取消远离名称。原因是.name-editor-form默认块级宽度配合input的flex-grow，没有编辑表单宽度上限。本次仅改shared/styles.css：整体表单width:440px／max-width:100%，输入继续占该范围的剩余空间；需求页头表单margin-inline:auto居中，文档表单保持左对齐，窄容器可收缩或换行。未修改业务命令、长度校验或用户数据。

本次`npm run format:check`及`git diff --check`均退出0，静态核对两处继续使用同一表单样式。低影响可逆CSS调整未新增测试、未重复类型／业务专项／构建，前述通过结果仍属于宽度反馈前；未运行浏览器，不将静态宽度规则称为实际布局验收。无本次临时文件或服务操作。

## 同日追加：编辑开关不改变布局

用户明确编辑框出现／消失不得导致页面跳动。原因：原组件条件渲染，用32px以上的输入行替换28px标题行，错误／核实反馈又在正常流中增加高度，实际页头ResizeObserver会随之重新分配空间。

修复：NameEditor常驻名称显示结构，编辑时visibility:hidden、inert及aria-hidden保留原占位；输入、按钮和反馈改为absolute编辑层，不参与父级尺寸计算。编辑层上限440px、max-width:100%，需求居中／文档左对齐，输入可收缩，按钮不换行，控件统一32px。输入focus使用preventScroll。DocumentMetadataBar将当前改名的错误／UNKNOWN／CONFIRMED恢复反馈移入同一层，非改名操作维持原反馈；未修改全局页头测量、固定页头尺寸或业务命令。

本次检查（代码在上次宽度修正之上，原未提交内容保留）：

- `npm run typecheck`及`npm run format:check`通过。
- `node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/property-edit.test.mjs tests/header-commands.test.mjs tests/v15-directory.test.mjs`：本次13通过、0失败，481.5126ms，不与前次13项累计。
- Python TemporaryDirectory内执行同前生产构建命令，受控随机输出前缀.name-stable-build-：1266模块、767ms、退出0；只有既有大chunk提示。清理确认True，未覆盖frontend/dist。
- `git diff --check`通过。静态核对显示层始终在流中、编辑层／错误层绝对定位，两个入口仍共用同一NameEditor；上述不等于浏览器位移测量。

隔离浏览器尝试与边界：仅构建临时内存夹具，禁止业务API和持久化，原生产服务未启停。初次辅助服务因非交互stdin的input()得到EOF退出，finally及TemporaryDirectory完成清理；改为最多600秒、停止文件结束的受控本机5192服务。首次夹具包含实际适配组件，后续简化夹具只复用真实NameEditor及CSS，拟比较页头／标题／元数据行／正文／滚动位置的开关前后坐标，未作为产品业务端到端。

IAB创建临时页导航http://127.0.0.1:5192返回net::ERR_CONNECTION_TIMED_OUT；阅读故障指引后，选择本机Chrome窗口时Computer Use明确因无法可靠识别Windows当前浏览器URL而停止本轮。没有继续UI输入，没有改用原始协议或其他技术绕过；没有实际页面交互／坐标结果，不能声称0px位移或浏览器验收通过。早先“本轮未运行浏览器”针对前段检查，这次是尝试失败而无有效证据。

清理核实：首次停止命令有PowerShell Split-Path参数兼容错误，随后已确认所属辅助进程退出且临时目录删除；最后一次使用Python核对规范化路径后写停止标记，进程正常退出、temporary_probe_removed=True，5192无监听且无.name-layout-probe-*目录。无用户业务数据变动、无模型／计数请求、无测试JSON／截图／录像／原始日志。后续需在可用浏览器中重新核对真实布局、焦点、长名称、窄窗及错误恢复。
