# V2.1本地AI试用启用记录

日期2026-11-19（Asia/Hong_Kong），分支codex/v2.1-design-review，保留既有未提交工作区。用户明确校准后单次复验通过即启用试用，明确火山北京接口和合成样本/通用Prompt/阶段指引/模板结构/输出Schema发送范围，密钥只认证；随后要求“别设置预算了”。本轮不增加代理层费用预算或反复询问预算，保留程序原生上下文/输出上限及已确认的一次验证、0自动重试。没有将该要求扩大为清除程序保护或擅自额外发送。

## 单次真实技术复验

唯一执行session70881，data/v21-ai-compat-05，报告[实际逐项记录](ai-compatibility-default-2026-11-19-v6.md)及自动attempts/reviewer保持；默认v37 release491da1a44a0d28a4c2fb7fe7ad2a809fda7650610278c961c5178cf63d2ff5cf，输入清单evaluation-inputs-default-2026-11-19-v6.md原SHA65c2e9133ee7d1cf2a6481673114a23838650cfbeb1e5e14e4b678113bb3eaba。执行前全60样本/120候选原样重建后才发送，非正常用户需求/正文。

实际1模型请求/1必要计数、0重试，call_status与validation_status均SUCCEEDED，Run COMPLETED，finish_reason stop，自动状态OBSERVATION_FINISHED/当前样本LIVE_RETURNED。输入26483/输出726/合计27209 Token，发送前预计26890，gap1641处于本release2048预留内；所有原生硬上限保持。正文/Revision/步骤生命周期/原Closure保护PASS。余59 NOT_RUN，未执行长输出、未代填双人人工，不称整版验收完成。原-03/-04失败记录仍失败，不重新标为通过。

## 启用与数据保护

确认正常库无在途任务后，仅停止已核对的本工作区8001/PID460396。原后台宿主记录exit=-1，随后退出，未重启该旧宿主。正常库schema210/db21-r7、需求/文档各1、3个GuideRun均FAILED、LLMUse0。

利用原CollaborationAdmission.approve_saved_call，从-05/EV21-BLANK-01-DISCUSS/input.sqlite的LLMUse1导入同v37真实技术证据；在ProcessLock下执行，正常current读取为LIVE_VERIFIED，原require_live通过，未伪造供应方/计数审计或改固定准入源码。该操作0凭据读取/0供应方调用，只写正常私有准入侧文件，不复制评测需求进入用户库。

随后用既有data/service-runtime-v21/backend-ai-host.ps1隐藏启动宿主234740，venv启动器70136、实际8001监听Python28476，启动时间22:55:19。其ai-startup.py先核对同release真实准入，才从原项目本地文件读取WALLE_MODEL_API_KEY，启动原生backend.app入口8001/Schema210；同正常数据库/静态资源，密钥未打印/复制给前端。当前使用默认DeepSeek，保留原逻辑，不新增OpenAI实现。

前端5174/PID311404持续保留；旧2.0的5173/8000保持停止。页面入口http://127.0.0.1:5174/requirements。用户之前失败Run1/2/3没有自动重放，后续由用户发起新请求；未代用户提交正文或卡片。

切换前后对requirements、requirement_documents、revisions、guide_runs、llm_uses各表全行快照分别做内存SHA对照，全部一致，正常LLMUse仍0/在途0，保留正文/版本/历史。技术观察只存在隔离原审计，无新增“测试数据”进入正常库。

## 实际验证

- 原生服务日志显示startup complete/8001运行；默认ai-startup.py只读检查为LIVE_VERIFIED，credentials_read/provider_calls/service_started均0。
- 8001及5174代理/api/v1/requirements均success=True/items1；5174实际detail.tsx模块75502字节、FormationProgress导出接入存在。不是只凭HTTP200或磁盘源码推断页面可用。
- 使用已安装Playwright CLI0.1.24、独立TemporaryDirectory浏览器，只读打开实际5174列表及/requirements/1，进入“进展”Tab。实际title为WALL-E · 需求工作台，进展Tab1、body可见、pageerror0、业务writes0；拦截非GET/HEAD/OPTIONS及外部URL，未发送模型请求或修改业务记录。
- 浏览器会话关闭，临时profile/CLI快照等全部回收cleanup=True，无截图/录像/原始测试JSON或日志留存。常规后台服务日志及正常DB/审计依法保留。
- 本轮不改源码；继承校准候选已完成的57项/3子项与15项完整链离线证据，不冒充本轮重跑。[校准记录](ai-framing-calibration-2026-11-19.md)。

## 交付边界

2.1现在为本地AI试用已启用。该单例证实当前release的技术协议/计数路径可用，不能替代完整60样本语义、双人独立人工及长输出验收。仍保留程序按实际结构/来源/权限/用量拒绝无效返回的保护。没有额外模型试发、用户请求重放、Git提交/推送或正式设计合并。

用户新优先级为试用完成后再接OpenAI，DeepSeek保留；OpenAI尚未实施，应另先写独立迭代文档再新增路径。无需再等待本次启用确认。
