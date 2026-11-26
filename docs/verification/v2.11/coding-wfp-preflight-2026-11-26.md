# Windows 任务网络前置检查

2026-11-26，香港时间。V2.11 事项 22。检查本机 Windows 原生过滤层、已准备的部署范围及 8001 的公开资源选项。既有业务库只读。

- 在管理员进程中运行当前 `windows_wfp.py` 的只读 WFP 事务及其原生 `FwpmLayerGetByKey0`，对 IPv4、IPv6 的连接、监听、接收共六个 ALE 层校验实际层类型及必要字段。六项均通过，层 ID 互不相同。Windows BFE 和 Defender 防火墙均为 Running。第一次探针启动因 Windows 命令长度上限未执行；压缩相同只读输入后成功。临时目录已清理。
- Windows 平台前置通过。尚未配置 WALL-E TASK 的受管 WFP provider／sublayer、任务专用规则及实际 OpenCode 回环；也未生成 SYSTEM 专用运行证据。该观察只核对内置层及字段。阶段验收须实测任务控制／模型端口、其他任务／端口及直连拒绝。
- 现有 `review-reg-plan/guard-deployment.json` 的 task、runtime 和 checks 为空，目标安装根不存在。当前准备件只覆盖受管仓库登记。未向系统写规则，也未安装新方案。
- 8001 的仓库、执行配置、检查集及授权列表均返回 HTTP 200 且为空。配置选项的 EXECUTOR、PRICE、CAPABILITY 为零。MODEL 有三项均未就绪，GIT 一项也未就绪。冻结的初始目录拒绝其他未经验证的选项，执行配置就绪判断仍固定返回 false。基线快照要求已有执行配置版本。
- Coding 模型单独依赖实际供应方的用量、账户及价表证据。当前价格校验固定北京方舟渠道；页面现有 OpenAI 文档配置不提供所需的 Coding 价格和准入记录。未读取凭据或产生真实调用。
