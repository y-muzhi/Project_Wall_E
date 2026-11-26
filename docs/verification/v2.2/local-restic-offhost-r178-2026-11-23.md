# R178 固定远端快照发布与独立取回

2026-11-23，独立工作区 `output/v22-dev-isolated`，`codex/2.2`。依据后端 4.12.1、7.10 及架构评审 3.4。

- 固定维护命令 `publish-offhost-backup-snapshot` 读取原完整封存包，在写前持久保有原意图。已出现不明结果时只核对同一标签及快照，不自动写第二份。上传回执只说明有固定快照。独立验证命令 `verify-offhost-backup-snapshot` 检查源宿主与执行宿主的安装和实际机器身份，从确认的固定仓库读取原快照并在临时目录完整取回核对，再保存异机回执。
- 各主机的仓库密码及存储凭据只由固定非 root 维护身份从受保护文件取得。Restic 子进程使用明确构造的环境，仓库为固定 HTTPS COS 区域端点及独立前缀，DNS 桶寻址。未增加仓库初始化、清理、采购或浏览器凭据输入入口。[Restic 0.19.1 仓库配置](https://github.com/restic/restic/blob/v0.19.1/doc/030_preparing_a_new_repo.rst) · [腾讯云 COS 域名规则](https://cloud.tencent.com/document/product/436/102489)
- 后端 162 项及 16 个子项通过，修改文件 Ruff 及 `git diff --check` 通过。离线传输夹具驱动原发布与取回入口，验证实际临时文件、命令选择、错宿主／仓库拒绝、未知上传只核对、实际恢复副本篡改拒绝和原回执重读。未连接 COS，也未在独立 Linux 验证宿主运行新版。
