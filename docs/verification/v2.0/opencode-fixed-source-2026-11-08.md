# V2.0 OpenCode 固定二进制与协议来源验证

2026-11-08（Asia/Hong_Kong）。Windows／NTFS、固定 SQLite 3.54.1、现行 db20-r29。未改正式设计或 Schema。

- 官方 1.19.5 Windows x64 资产页的 SHA256 与设计一致。代码只接受固定 ZIP 原摘要，读取其中唯一根目录 opencode.exe 的有界原字节，核对 PE x64 及成员摘要，再与受信安装提供的本机程序进行原 NTFS 句柄核对。原生包与本地程序引用须与任务固定配置一致。 [官方发布](https://github.com/anomalyco/opencode/releases/tag/v1.19.5) [官方固定资产](https://github.com/anomalyco/opencode/releases/expanded_assets/v1.19.5)
- 下载固定提交的实际 OpenAPI 原文到临时目录，执行 tools/check-opencode-binary.py --openapi。1063359 字节及 Git blob e064da66bda63c78272f398c940755ecf68b0a3f 相符，设计采用的 17 个方法／成功码通过，包括 prompt_async 204。该文件证明固定协议来源，实际服务协议需独立验证。 [固定提交 OpenAPI](https://raw.githubusercontent.com/anomalyco/opencode/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/sdk/openapi.json)
- CHECK_CONDITIONS 私有安装接受可选二进制及原 OpenAPI 来源，记录两个独立布尔事实。默认缺受信安装时两项为 false；旧启动条件回执保持可读。通过静态来源核对仍需实际运行依赖、只读目录、LPAC／WFP、服务身份及供应商准入，未触发 START_INSTANCE。
- 实际测试使用临时 NTFS ZIP 与 x64 PE 夹具验证摘要、版本与原引用、歧义 ZIP、文件锁、改写拒绝及取消；首轮 26 项通过，100.48 秒。默认缺安装的真实 Guard／MinGit 组合 1 通过，202.29 秒。加协议原文后定向 28 项通过，83.56 秒；同一版本以真实 Guard／MinGit 再验证缺安装分支，1 项通过，190.18 秒。
- 官方 ZIP 直连的 HEAD 和 GET 均超时，发布站文件路径返回 404；GitHub 官方发布接口返回 HTTP 504，未取得可供核对的 Windows ZIP。实际二进制包与运行版本仍待核对。仅只读核对公开资料、临时文件及隔离数据库，未启动 OpenCode、变更系统权限或更新用户服务。
