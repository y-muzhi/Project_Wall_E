# DeepSeek简短调用测试（2026-10-07）

用户已在本机`.env.local`配置密钥，并要求：“模型要用DeepSeek的4.1 Flash，并且调用的轮数和字数你自己设置上限，不允许一直调用，仅作调用测试”。沿用此前火山方舟供应方，正式模型ID依据[模型公告](https://docs.volcengine.com/docs/ark/model-release-announcement?lang=zh)为`deepseek-v4-1-flash-260910`，北京Chat端点。官方[深度思考说明](https://docs.volcengine.com/docs/ark/deep-thinking?lang=en)支持disabled，[Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=en)说明该模型max_tokens限制回答和思考总长度。

每次单独获授权的测试最多1次Chat、0次Tokenization、不重试、不跟随重定向，关闭思考、非流式、输入正文55 UTF-8字节、max_tokens=128、最长45秒、响应容量64KiB。凭据只在明确执行分支从被Git忽略的`.env.local`读取，按单个赋值解析，文件内容不作为代码执行，密钥不进入命令参数/输出/提交。独占准备与结果文件保留；同一attempt目录不允许重发，准备不是已发送或费用证明。

第一次实际请求：`model-smoke-real-2026-10-07.json`，404/ModelNotOpen、456毫秒，停止。随后用户明确：“我搞错密钥了，重新配置好了，你再继续试试”，仅新增授权1次同上限测试。工具重新读取本机配置，第二次结果：`model-smoke-real-attempt-2-2026-10-07.json`，404/ModelNotOpen、395毫秒，停止。累计2次实际Chat调用、0次计数、0次自动重试，费用未知。没有执行此前Doubao的6＋6观测，也没有因失败换供应方或模型。

[火山官方错误表](https://docs.volcengine.com/docs/82379/1299023)定义404 ModelNotOpen为当前账号未开通对应模型。需要在供应方控制台开通；本轮不会继续付费调用。结果仅证明收到这个错误，未证明模型生成、业务效果、准确计数或生产兼容。

独立离线记录`model-smoke-offline-2026-10-07.json`及`model-smoke-offline-attempt-2-2026-10-07.json`保存7项实际工具测试与默认CLI原始输出；覆盖固定参数、错误/重定向不重试、超时未知、错误模型、凭据回显脱敏、响应容量、本地重复凭据拒绝和独占记录。此前9个内联离线检查也通过，但没有将其说成正式后端测试。两次实际请求间只加了明确的第二attempt槽位，没有再次运行第一次。

这是独立诊断工具，不改D-007/D-011历史冻结资源、公开接口、正常业务库或当前用户服务；DeepSeek只用于本次授权的调用测试，既有程序预算不被短测试参数替代。

第三次独立授权：用户原文“我开通了，你再试试”。仍只发送1次相同短请求、不重试，完整结果保存在`model-smoke-real-attempt-3-2026-10-07.json`。HTTP 200、返回model精确为`deepseek-v4-1-flash-260910`、assistant.content为`OK`、finish_reason为stop，1291毫秒；实际usage为输入19、输出1、总20 token，费用未知。本次调用测试通过并结束，累计3次Chat（两次ModelNotOpen、一次成功）、0次Tokenization、0次自动重试；不会继续执行旧6＋6计划或追加请求。前文两次失败的停止状态保留为历史事实。

最终工具7项离线测试与默认inspect记录见`model-smoke-offline-attempt-3-2026-10-07.json`，真实请求数0；当前命令只提供这三次已明确授权的固定槽位，同槽位重复执行拒绝。这一次短回复的成功不是六任务实际生成/效果、准确计数或生产封装兼容证明。
