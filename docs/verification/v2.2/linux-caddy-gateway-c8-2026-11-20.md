# WALL-E V2.2 Caddy 与两套普通服务验证

2026-11-20（Asia/Hong_Kong）。Ubuntu 24.04 ARM64 专用验证机。使用现有 C1 两套受管安装及原固定程序候选，部署所用程序、Schema 和各套库继续保留。操作限本机回环 9443、两处 Unix 套接字和本轮唯一临时证书资料目录。

- 下载了 `caddy_2.6.2-6ubuntu0.24.04.3_arm64.deb`。Ubuntu APT 索引中的 SHA256 为 `83c00e66c175a8f86c5085a0a67c802cc72f7b43bb4f55eae024041a3e6ac686`。实际包复核一致。用 `dpkg-deb -x` 提取的 Caddy 报告 2.6.2，二进制 SHA256 `6da742da7bb1a73f89c01a1e098aaa5df3ba0f4dab4cbf229b614ea5d4030a3c`。系统服务及系统信任库保持原状。
- 实际 `caddy validate --adapter caddyfile --config <临时Caddyfile>` 成功。首次资料未按项目规范 JSON 编码，生成器拒绝。修正后发现 root 私有 FD 经 /dev/stdin 重新打开仍受权限检查，验证先用 root 发布、专用网关组只读交付解决。产品生成器接续加入受保护 setgid 目录及组校验，新的固定安装另验。
- 网关独立 UID 42551，持 42531、42541 两个连接组。C1 的开发与集成原安装分别获得实际新 run。Python TLS 客户端仅载入该入口临时 CA，并按真实 SNI、证书名和 Host 连接。两个站点均通过 Basic realm、公开配置与响应身份吻合、WEB／AUTOMATION 握手、来源错误拒绝、来路伪造 principal 被认证身份替换、各自静态根及未知 API 路由的核对。对方凭据返回 401。系统缺省 TLS 信任仍拒绝测试 CA。
- 验证结束按本轮进程及私有套接字真实归属关闭 Caddy 和两套应用，复核原运行套接字消失。记录没有口令、原始请求、原始进程日志或证书私钥。

本单元验证了实际网关至两套真实应用的 TLS、代理及认证。Windows 本机 HTTPS 浏览器页面成功流程、C8 新构建的端到端重启和新生成器组校验继续实施，范围与离线和真实 Chrome 夹具证据分别记录。
