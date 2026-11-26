# R482 Linux V2.2 固定 Schema 基底

2026-11-26（香港时间）。开发工作区 `codex/2.2` 与集成工作区 `codex/2.2-integration`。

R480 更新 Windows 默认 Schema200 指针后，Linux V2.2 普通安装的 Schema 构建在无网 Ubuntu x86_64 TCG 来宾内报 `Unexpected original Schema200 release`。Linux 以原 `db20-r50` 的 72 表／299 对象结构为基底，同时引用了会随 Windows 默认版本变化的指针。

`schema_v22_release.py` 现独立固定 `db20-r50` 及其原清单摘要 `10ff02e670eb705e6ac537eb9335449a72de9dbc93eeffbe46b16d7d74557f31`。生成清单与校验基底使用同一固定值，且继续校验原 SQL 和对象字节。两工作区 Windows 默认指针仍为 `db20-r51`。既有候选 Schema 专项改为按候选清单读取基底，并核对固定版本和清单摘要。

两个工作区各自执行 `python -m pytest backend/tests/infrastructure/test_v22_candidate_schema.py -q -p no:cacheprovider`，各 1 项通过。相关源码和专项 Ruff 格式检查及两侧 `git diff --check` 通过。修复后的 Ubuntu 来宾从两个程序目录实际生成 V2.2 FRESH_ONLY Schema，结构摘要均为 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。两侧 Windows 分别用固定 SQLite 和 `load_release()` 读回 `db20-r51` 原摘要。应用、资源、Linux 工具、共享代码和前端范围内共比较 1,607 个文件，两工作区逐文件一致。主工作区的五份 V2.01 原设计摘要与实施基线一致。

最初 QEMU 固件路径使用含中文的绝对路径，改用相对路径后正常引导。应用寿命周期随后实际完成启动，Unix 探针先用错协议，在修正为上游 HTTP 后两站均返回就绪。首笔合成需求标题超过 20 字，被正常返回 422 `TOO_LONG`，下一次使用符合契约的标题。浏览器仍通过真实 HTTPS 网关验证。

## 当前源码普通应用实测

独立无网 Ubuntu 24.04 x86_64 TCG 来宾，新增专属 QCOW2 覆盖盘，历史镜像只读。分别从两个工作区物化程序树及各自前端产物，建立两个环境根、应用与维护 UID／GID、入口组、Schema、配置、稳定锁、Unix socket 及独立数据。按产品 `runtime.py environment prepare/continue` 初始化，再按 `serve_environment.py prepare-start/serve` 启动。两站原入口返回就绪。两站通过真实 Unix HTTP 分别创建需求、空白文档、保存草稿并完成编辑，读回各自正文。互换环境 ID 或数据代次分别返回 409 `ENVIRONMENT_MISMATCH` 和 `DATA_GENERATION_MISMATCH`。开发应用身份不能读取集成数据库文件。

验证脚本前期的合成编辑区块使用了拒绝所有来源的验证函数，实际校验返回来源非法。改用项目既有 `DocumentSources`，绑定测试库真实编辑会话后通过。另一次来宾启动等待超过 125 秒，测试脚本用 260 秒的有界就绪等待重跑。两个普通应用均完成启动。

开发服务停止后用新运行 ID 开放并读回原正式正文。集成服务在开发重启期间保持运行并读回自己的正文；正式网关生成器根据两份实际安装记录生成双站 Caddy 配置。集成站也在正常停机后重新启动并读回原正文。两站重启读回通过。TLS 探测脚本错误使用未实现上下文管理器的 HTTPSConnection，浏览器未进入业务步骤。已修正测试连接关闭方式，R483 单独执行真实 HTTPS 双站浏览器路径。该轮来宾正常关机，临时覆盖盘和启动介质已回收。
