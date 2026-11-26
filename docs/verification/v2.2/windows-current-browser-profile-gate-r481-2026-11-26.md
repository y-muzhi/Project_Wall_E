# WALL-E V2.2 当前源浏览器入口与 profile 隔离（R481）

日期：2026-11-26（香港时间）

## 临时服务及浏览器范围

在开发和集成工作区分别创建全新 `db20-r51` Schema200 临时数据库，启动当前 SPA 静态构建及 `create_app` 的临时本机服务：开发 18101、集成 18102。服务各自使用独立数据库。用命名 Playwright 会话 `walle-v22-r481-dev`、`walle-v22-r481-integration` 及两个全新持久 profile 打开实际首页。首页和静态资源加载，页面标题为 `WALL-E · 需求工作台`。

## 环境准入结果

前端随后请求 `/.well-known/walle-environment.json`。两个临时服务均返回 404，界面显示“当前环境尚未就绪。请稍后重新核对连接。”。本轮临时 harness 没有真实安装的普通环境对象、HTTPS 公共来源、有效环境绑定清单或 Unix 私有准入通道；入口校验按设计拒绝了业务页面访问。这里的 404 是临时服务没有安装环境配置的证据，不是已安装产品返回异常。没有伪造握手、拼接身份或直接调用业务 API，因此需求／编辑／刷新业务流程未通过，也未宣称通过。

## 浏览器状态隔离

在开发 profile 的临时 `localStorage` 写入 `__walle_r481_profile_check=dev-profile`，同一 key 在集成 profile 读回 `null`。两个命名浏览器会话和 profile 确认没有共享本轮浏览器存储。该标记不是 WALL-E 业务数据；关闭会话并删除 profile 后一并清除。此结果只覆盖浏览器配置隔离，不覆盖业务工作流或不同 Linux UID 的浏览器进程隔离。

## 清理与下一步

关闭两个 Playwright 会话，按本轮 owner 标记核对并终止临时服务 launcher／listener 进程，确认 18101／18102 无监听、8001 仍由原 PID 提供；删除两套临时 SQLite、锁、日志、profile、专用 npm cache 和本轮生成的两份页面快照／两份 Console 日志。没有留测试 JSON、截图或原始日志。

下一步必须在两个独立的 Linux 普通安装环境中使用真实的安装绑定、独立配置／Schema200 数据、私有准入 socket 与 HTTPS 网关，让 `.well-known/walle-environment.json` 和服务端握手都由固定环境提供；再用独立浏览器完成创建需求、创建／编辑保存文档、刷新读回及跨环境拒绝。同时验证安装 UID、组权限和 Unix socket 拒绝边界。未准备好这套安装时保持该项未验证，不放宽准入。
