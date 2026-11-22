# WALL-E V2.2 普通环境能力准入 C9

2026-11-20（Asia/Hong_Kong）。专用 Linux 开发工作区 `codex/v2.2-development`。C9 复核当前普通环境握手、实际后端开放动作和前端第 4.2 节。应用接入请求前准入，卡片提交、模型及执行动作在传输前被拒并保留原冻结请求。实际管理、模型和执行权限仍由后端独立判断。只读浏览、评论索引／消息、版本读取及普通文档写入保留。

- Windows `node --test tests/environment-binding.test.mjs` 13 项通过，覆盖实际普通动作表、卡片冻结后未发送、无服务回执和旧无绑定客户端入口。
- Linux `node --test --test-timeout=12000 --test-reporter=spec tests/*.test.mjs` 595 项通过。第一次将限制接到所有低层绑定传输，破坏既有冻结 Coding 命令验证；调整至已挂载应用的连接所有者，在绑定后端服务仍独立拒绝。最终 595 项通过，没有跳过。
- `npm run format:check`、`npm run typecheck`、`npm run build -- --logLevel warn --outDir <独立产物>` 通过，C9 输出为 `~/walle-v22-validation/scopes/development/web-c9-capabilities`，120 文件。Vite 仍提示个别产物超过 500 kB。

C9 另在两套独立 HTTPS 安装验证固定静态摘要 `24465d4c4665f7666020cbf3c0895f9a058249c5756fe1f92a1ba5611f9fa7b5`。两份隔离 Firefox 在真实页面完成创建、人工保存、结束与重读，核对需求名称／状态、文档确认、版本说明、代码开发、测试和设置的禁用原因。评论索引、消息及版本实际读取，模型／卡片提交和运行请求未发出，直接进入 `/testing` 显示未开放并可回工作台。网关、后端、9443 转发、浏览器及临时资料均关闭。已保存结构卡片样本、只读主体和运行中数据换代仍待另外验证。C8 的实际同代次重放保护见 [浏览器证据](windows-firefox-https-c8-2026-11-20.md)。
