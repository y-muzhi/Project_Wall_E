# 区块悬停与折叠动效优化检查

日期：2026-10-30。M15-FOLD-UX-02。代码状态：HEAD33a6736加原未提交选区／折叠／名称修改及本轮增量，原改动保留。正式FE／BE1.0／EFFECTIVE及冻结资源不变，来源摘要沿当前断点；规则见[专项](../../archive/iterations/v1.5/WALL-E.区块操作悬停与折叠动效优化_V_1.5.md)。

实现与核对：

- navigation.ts的blockControlPositions统一六点与箭头的首行中心，读取实际line-height／padding，两个24×28按钮相隔4px，箭头右端距文字8px，与高亮4px外延另留4px。styles.css显式min-width:24px和居中，覆盖公共.icon-button的28px最小宽度；独立白底／中性悬停底。正文／大纲使用同一right图标按aria-expanded旋转，保留reduce规则。
- BlockAuxiliary以按钮／菜单作为同一悬停区域，离开后120ms关闭，跨隙进入另一侧取消关闭；点击不锁定鼠标菜单。键盘激活／ArrowDown、菜单导航、Esc及触摸替代入口保留，焦点移出关闭；目标改变、toolbar消失和卸载清理关闭计时器及待执行焦点RAF。来源弹层仍独立，旧菜单入口卸载后关闭来源可回六点按钮。
- 新shared/disclosure-motion.ts采样当前高度、上下边距／内距、边框和透明度，先采样再取消，批量读自然尺寸后启动WAAPI，避免每段读写交错；统一motionTiming.disclosure=180ms及原缓动。完成与未完成轨道分别记录，全部结束后应用最终显隐并取消所有fill:both效果；旧完成回调由generation隔离。reduce、resize、能力缺失／异常、离屏节点、dispose均落到最终状态并清理RAF／动画／监听。
- DocumentSectionVisibility复用该公共方法，外置作用域CSS保留运动中的节点、最终才display:none，隐藏集立即pointer-events:none／interactivity:inert；运动中禁用该宿主的overflow anchoring。原自动高度／display插值和专属计时器删除，不向ProseMirror区块写class/style。折叠范围、状态、定位及隐藏编辑保护仍沿原导航，动画不延迟业务状态。

环境及授权：Windows PowerShell、Node24.15.0及锁定依赖；前端strict／未使用检查保持。离线专项及构建加载tools/quality_node.cjs阻断真实网络。未改业务数据、未启停用户服务、未触发模型／计数，不提交推送。

实际检查：

1. 第一轮5文件20项为19通过／1失败：旧section-navigation测试假定原CSS计时器仍存在，替换实现后无DOM的降级分支立即完成，回调计数3与旧断言2不符。按H11删除被替代计时器专属断言，改验无DOM立即落位／无排队工作，并新增公共动画边界专项，没有保留旧兼容分支。
2. 修正后6文件26项通过，0失败，499.3083ms；此时新增公共动效5项。随后补充“已隐藏轨道与中断轨道共存时仍保持零高度”第6项，覆盖零尺寸轨道不能因跳过动画而短暂露出。
3. `node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/*.test.mjs`：本轮438通过、0失败、9470.8396ms。检查覆盖原折叠范围／嵌套／定位／隐藏编辑、选区、原动效及其他前端回归，不与历史430项相加。
4. 最后按正式SHR-MOTION复核，公共内容动画时长从初写的layout档220ms改回disclosure档180ms，不改全局时长。最终运行`node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/disclosure-motion.test.mjs tests/section-folding.test.mjs tests/section-navigation.test.mjs`：13通过、0失败、437.2487ms；未为这一常量修正重复整套438项。
5. 最终`npm run typecheck`及`npm run format:check`通过。没有any、忽略检查或关闭strict。`git diff --check`通过。
6. 临时生产构建由Python TemporaryDirectory包裹，先核对输出为frontend内.fold-ux-build-*：`node --require ../tools/quality_node.cjs node_modules/vite/bin/vite.js build --outDir <受控临时目录>`。最终1267模块、768ms、退出0，只有既有大chunk提示；清理确认True，未覆盖frontend/dist。此前同轮构建3.47秒属于收尾时长校正前，不重复累计。

未覆盖与浏览器边界：本轮没有操作浏览器。上一任务IAB本机连接超时、Windows Computer Use因无法可靠识别当前URL而停止的现场仅作环境背景，本轮未重试该UI链路，也未改用其他技术绕过。不宣称真实按钮布局、悬停移入／移出、跨隙速度、动效中间帧、滚动／IME、多浏览器或产品端到端验收通过。几何函数及动画模拟证明程序边界，不能替代真实视觉证据。

清理及保存：只保留本Markdown，不留测试JSON、截图、录像或原始日志。临时构建已清除，无本轮测试服务遗留。正式设计归并仍待后续文档收口。

## 同日追加：用户正在访问的5173源码核对

用户反馈本地页面似乎未改变，询问是否未提交；随后明确当前地址为http://127.0.0.1:5173/requirements/1。本轮仅核对现有运行前端，不提交Git、不启停服务、不重建dist、不读写业务接口或调用AI。

首次沙箱内Get-NetTCPConnection未得到现有服务，CIM访问受限，Python回环HTTP返回WinError10013；这些属于访问限制，不能据此判断用户服务不存在。通过审批后的沙箱外只读检查，确认127.0.0.1:5173监听PID14996仍在，页面HTML返回200并含/@vite/client及/src/main.tsx，属于源码开发服务。再次只读获取navigation-view.tsx、disclosure-motion.ts、navigation.ts、section-folding.ts、styles.css均200，已包含本轮菜单离开关闭、首行对齐、24px最小宽度、DisclosureMotion及180ms公共时长、名称浮层等代码。

服务返回的CSS源路径确为当前工作区C:/Users/羊牧之/Documents/ChatGPT/Project_Wall_E 2/frontend/src/shared/styles.css；相关响应Cache-Control:no-cache且带ETag，源码没有serviceWorker注册引用。frontend/dist的旧日期不属于用户5173开发入口，不以重新构建生产目录解决该问题。Git HEAD仍33a6736，修改是本地未提交状态；Git提交不控制Vite读取源码。

确认范围：已证明运行服务在返回新源码，尚未证明用户现有标签页已加载或执行新模块。已请用户Ctrl+F5完整刷新后复查；旧标签页缓存／HMR保留导航实例只是待核实原因，不能当作已定位事实。未重新尝试上一轮停止的Windows UI链路，不新增浏览器视觉通过结论。本轮无代码修改、无新测试产物、无服务更新。

用户后续确认：针对上述完整刷新及区块菜单／折叠复查问题，明确回复“刷新后已更新”。这证明用户完整刷新后已能看到本轮修改，结束本次“页面是否加载新代码”的核对；不据此宣布全部交互／动效中间帧或多浏览器专项通过，也不能单独区分缓存、HMR旧模块或旧实例的具体原因。仅更新文档，源码及Git提交状态未改，未启停服务或执行新产品检查。

## 同日追加：按钮与标题间距再次加宽

用户新截图仍认为六点／箭头／标题太近。本次两按钮之间4→8px，箭头右端距文字8→20px，避开高亮4px外延后另留16px；正文沟槽60→76px，定位偏移同步76px、按钮步长32px，保留六点原横向位置，正文统一右移16px。按钮尺寸、首行中心、菜单和折叠规则不变。仅改navigation.ts、styles.css及原navigation.test.mjs几何期望，不新增镜像测试。

本次`node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/navigation.test.mjs tests/section-navigation.test.mjs`：6通过、0失败，741.8106ms；`npm run typecheck`、`npm run format:check`及`git diff --check`通过。经审批后在沙箱外只读GET现有5173的/src/documents/navigation.ts和/src/shared/styles.css均200，分别包含block.left - 76／left + 32及76px正文左内边距，确认运行服务返回本次源码。

低影响间距修正未重跑全量、构建或浏览器，原438项及生产构建不当作本次新结果；没有服务启停、业务数据／模型调用或测试产物。已提醒用户Ctrl+F5完整刷新查看，尚无本次加宽后的视觉验收证据。
