# V2.1首次AI运行CONFIG_INVALID诊断

日期：2026-11-18，Asia/Hong_Kong；13:36只读核对。用户截图为“本次运行失败：所需协议或模板资源不可用”。本轮仅诊断，不重新发送请求、不修改业务记录或启用真实调用。

## 已确认事实

- 服务仍运行：后端8001/PID460396、前端5174/PID311404，宿主178388；没有重启或改动服务。
- 本工作区GuideRun1为DISCUSS/collaboration_v1，FAILED/FINISHED，error_code=CONFIG_INVALID。
- 同库已有需求1、文档1、在途GuideRun0；这些是用户建立的正常记录，不再是可清理的初始空库。
- llm_uses为0，计数审计prepared/finished文件均0，未发生模型或计数API调用。
- 生产ResourceCatalog成功加载v27，release SHA e5e0860a49812006f72d6f0de3f7d3c06420d87b8e7a45f683d9e50d52769bfe，状态OFFLINE_READY；协议/模板资源并未加载失败。
- 当前服务宿主清除继承的模型凭据，仅配置本工作区数据库/静态资源；工作区.env.local不存在，原生入口不自动导入原工作区密钥。没有读取密钥内容。

## 实际拦截点

orchestrator在PREPARING首先执行ModelProfile.from_environment；当前未配置WALLE_MODEL_API_KEY，抛ConfigInvalid，随后以CONFIG_INVALID保存失败。共享错误文案把该错误泛化为“所需协议或模板资源不可用”，因此不能据截图认定资源文件缺失。即使配置凭据，新v27仍需对应真实准入，不能借旧release的LIVE放行。

本轮未改写历史Run的错误信息、未清pending输入、未重新派发、未复制旧准入或改用替身。默认评测清单-r2的Recipe SHA仍与当前源码相同，无需机械重跑已完成的离线输入构造。

## 接续边界

当前启动的是可读/可人工维护的HTTP服务，AI执行尚未开通；重复发送不会自行恢复配置。后续启用需要明确凭据来源及当前真实验收次数/预算/重试边界，再按现有[操作说明](../../project/v2.1/模型评测实施说明_V_2.1.md)完成对应Profile/release的真实准入。原宿主会清除父进程WALLE变量，不能只在另一个终端设置环境变量就假定已对现进程生效。

不得因这一通用文案重建数据库、覆盖协议/模板、重试付费请求或伪造LIVE。本轮没有产品源码改动、服务更新、真实API或提交推送。凭据/准入缺失与提示文案过于笼统分开记录；文案进一步细分若实施，须先独立迭代，不把它当作AI已经可用。
