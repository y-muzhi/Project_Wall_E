# R166 固定候选的验证域名

2026-11-23，独立工作区 `output/v22-dev-isolated`、`codex/2.2`。依据 V2.01 后端 4.11、6.3、8.2。

- `python -m pytest -q backend/tests/infrastructure/test_v22_business_origin.py` 共 5 项通过。读取真实保护计划和固定访问策略，验证按相同计划重入、计划字节变化、已登记入口变化和非法通配的拒绝。Windows 专项适配了 Linux 根权限和 ext4 观察。
- 使用工作区自身锁定前端依赖，Vite 普通／管理分别输出到 `output/build-codex-2.2-r166/ordinary` 和 `output/build-codex-2.2-r166/management`。普通 120 文件、入口 SHA256 `21316a208e6c3ac9055d83f93e115203496399bfdd5a9f28572a9cf2dca0c089`，保留既有主包体积告警。管理 3 文件、入口 SHA256 `32b6c96a846b55d0fb6391d1b37bfdc64745daf20e9ebf3df516623a1b4a570a`。
- 产物为本地独立构建。固定候选原生安装、宿主 TLS、云配置与生产控制依赖实际准入证据。
