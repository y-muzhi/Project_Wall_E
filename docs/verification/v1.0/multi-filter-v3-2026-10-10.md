# UX-024 多选筛选基础检查

日期：2026-10-10，Asia/Hong_Kong。

范围：MultiFilter草稿、提交／撤销、空选与全部、外部条件变化；筛选入口底色、选中行间距；工作台和运行历史四处共享入口。仅本轮前端基础检查，不恢复完整业务验收。

|命令／检查|实际结果|
|---|---|
|frontend目录 `npm run build -- --logLevel warn`|通过，含TypeScript及Vite生产构建，components-probe变更也在类型检查范围；既有超过500kB产物提示保留|
|`node --check tools/verify-components-browser.mjs`、`node --check tools/verify-workbench-browser.mjs`、`node --check tools/verify-api-browser.mjs`|通过；三个工具只改既有筛选操作预期，未执行会生成证据文件的完整流程|
|Playwright CLI独立临时会话，5173/tests/browser/components.html|13组基础交互通过，父级总共只收到四次预期筛选通知，数字0完整保留|
|默认全部及空选|默认仅全部勾选，无全选按钮；取消全部的空草稿与全部等价，无回调；取消最后具体项允许，关闭后发送完整选项数组及all=true；空受控数组可以打开|
|延迟提交及取消|勾选期间无回调；点击外部聚焦元素只回调一次，覆盖pointerdown和blur同次触发；入口关闭及Tab离开分别提交；Esc取消并还原入口焦点|
|旧草稿失效|父级实际筛选值改变、可选值改变或禁用时丢弃草稿；卸载也不提交。勾满具体项与已提交全部等价，不重复通知|
|实际样式测量|展开入口背景rgb(255,255,255)、边框rgb(54,94,220)；两个连续选中行背景rgb(237,242,255)，边缘间距4px、圆角8px|
|8000/requirements，需求状态／类型|勾选期间零次列表GET；点击外部后各一次GET；条件不变再次开关无GET。实际提交状态INITIALIZING＋ACTIVE、类型NEW，均page=1|
|8000/requirements/2，运行状态／操作|勾选期间零次运行列表GET；关闭后各一次GET；无变化关闭无GET。实际提交RUNNING＋WAITING_USER、操作ASK，均page=1|
|限定本轮文件 `git diff --check`|通过，无空白错误|

失败及调整：首个临时CLI脚本保留换行，run-code出现Unexpected token，改用单行后成功。首次实际页面检查把默认隐藏的运行历史当可见节点等待，超时；调整为先打开AI助手。第二次读取初始aria-busy=false，运行历史请求尚未启动就取路径，检查失败；调整为等待实际运行列表响应完成，再检查筛选。上述是观察脚本前置问题，未改变业务状态处理或伪造通过。

组件夹具只操作内存；实际页面浏览器拦截所有非GET API请求，仅查询和局部布局偏好，没有编辑用户需求、发消息或调用模型。构建dist已更新；开发服务使用当前源码。

所有成功、失败会话均在finally关闭；临时目录绝对父路径及walle-filter前缀核对后删除。不保留测试JSON、截图、录像或原始日志，仅本Markdown记录结果。

未执行全套历史浏览器工具、全部查询失败／分页组合、移动端触摸、跨浏览器和辅助技术验收。窗口失焦不提交由relatedTarget非空限制实现，本次未额外模拟操作系统窗口切换。局部基础检查不代表全功能验收。原前后端设计和originals归档本轮未修改。
