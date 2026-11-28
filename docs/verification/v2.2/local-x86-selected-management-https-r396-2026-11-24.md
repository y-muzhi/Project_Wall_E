# R396 恢复后实际管理 HTTPS 入口与原键查询

2026-11-24（香港时间）。从 [R395 的真实活动新锚](local-x86-active-registry-anchor-r395-2026-11-24.md) 继续。无网卡 Ubuntu x86_64、固定 CPython 3.13.18／SQLite 3.54.1，真实 Caddy 和管理应用各自独立进程，9444 仅来宾回环，管理及业务 Unix 入口分离。

- 当前固定管理前端从独立 Windows 工作区重新构建，TypeScript 和 Prettier 通过，产出 3 项文件。固定索引逐项钉住并校验。实际 `prepare-registry-recovery-entry` 和 `admit-registry-recovery-entry` 依新锚、原选择、独立网关 UID 和实际入口生成固定配置，同键重放一致。接纳回执 `315f5de04b83fb7e7533e439696b2c0acbf16d18700a5f17d95d3f809ba314ea`。
- 通过来宾专属 CA 实际建立 HTTPS。读出新管理公开配置、管理身份和两套受管普通环境。根页面和固定 JS／CSS 均逐字节匹配真实构建。原两项 ATTACH、START 和 STOP 通过 `prior-registry/.../operations/by-key` 按旧代次和原键读取。
- 旧代次请求绑定收到 409 `MANAGEMENT_SCOPE_MISMATCH`。正确新代次在暂停时可读，新的管理写请求收到 503 `MANAGEMENT_DISPATCH_PAUSED`。管理动作显示不可用。实际原锚归档、活动锚、旧暂停、两个管理库、两个业务库与锁保持原字节和身份。
- 初次脚本使用了普通页面的列表字段，调整为管理接口的真实 `environments` 结构。最终 `r396-webread` 退出 0，两个所属进程退出、管理 socket 消失。管理写入恢复继续按新鲜宿主核对和实际开放入口独立验证。
