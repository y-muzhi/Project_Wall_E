# WALL-E V2.2 最新固定包与 HTTPS 文档闭环

2026-11-20（Asia/Hong_Kong）。专用 Ubuntu ARM64、Caddy 2.6.2、回环 9443。首先以前一固定包验证真实 TLS 接入，见 [Caddy 入口验证](linux-caddy-gateway-c8-2026-11-20.md)。

- C8 的固定程序包摘要为 `bb2fcda033aaff8640656916ef2380ce7ca9babdf966c79a2ec136bdba550471`，两套独立静态根摘要均为 `88765a4c735ebb754c8c4afa194abb63cbce8cb7a8e9c93f8085ae419fa49225`（120 文件）。旧 Schema 发布摘要与新程序针不一致时，新安装拒绝绑定数据库。以新程序重新发布 FRESH_ONLY Schema 摘要 `8670cf84407b37a93666e2e35109dff590e5d40f2302c1e1a4de62dbf02b15be`，实际对象摘要 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。保留旧诊断现场，在独立根建立两个新锚点。
- 安装位于 `/opt/walle-v22-validation/environments-c8s-r3`，开发实例 `7a36a730-3a3a-4568-a791-d1188d529e86`，集成实例 `b8867099-2362-473f-9423-5c3708e3825b`。Caddy 专用 UID／GID 42691，经 42651 和 42671 连接组访问后端。生成器在 root 受控目录发布 `0440` 的网关配置，Caddy 在实际独立身份下执行 `validate` 成功。
- Python TLS 客户端仅载入本轮 CA，实际验证两个主机名、身份隔离、认证 realm、WEB 和 AUTOMATION、真实来源拒绝和网关去除外部认证头／伪造身份。两套 HTTP 操作分别创建需求与文档、开始并保存编辑，重新启动得到新运行标识、读取原草稿、用同一原键重查同一事务结果，再完成编辑及读取 CURRENT。两套库相同需求、文档和草稿编号拥有不同正文。错环境绑定及重复绑定头均被拒绝，对方凭据返回 401，系统缺省 TLS 信任拒绝临时 CA。
- 完成后按实际拥有的进程和私有套接字关闭网关及两套应用，无遗留套接字。范围为真实 HTTPS 接口与应用持久化。普通页面的跨环境及断线编辑验收另记。
