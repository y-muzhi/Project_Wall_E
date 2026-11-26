# 普通环境受信 HTTPS 入口接续 V2.2

2026-11-20。接续 V2.01 后端 6.1、6.3 和前端 6.1 的本机首批入口。此记录用于隔离验证，正式规格保持原样。

- 后端、维护与 HTTPS 入口使用不同身份。可被入口访问的环境为 Unix 套接字另分配连接组。入口身份仅获套接字目录遍历和连接权限，不属于该环境的数据、锁及控制共享组，也不拥有运行目录。
- 固定候选验证优先使用两套已经构建的静态前端。站点和自动化访问身份分别固定，独立于构建产物提供公开描述。开发模块和 HMR 需另行验证专属入口，当前范围未启用。
- Ubuntu 24.04 仓库 Caddy ARM64 候选仅在专用验证目录提取并核对摘要。2.6.2 使用原指令名 `basicauth`。测试证书通过本地 CA 签发，不改变宿主证书库。Windows 浏览器信任、作用域存储和页面实际操作另行验证。
- 生成器仍由 root 核对 installation 与凭据摘要。实际网关使用通过受保护的 setgid 配置目录交付的只读组文件。网关主组不兼任业务库、稳定锁或控制目录共享组。后端拒绝入口未清洗的授权、转发与认证保留头。

## R192 各环境独立程序的入口生成

复核后端 4.11、6.3 与 7.10。R191 开发和集成已有各自封存程序根。原普通入口 `--site` 却把单个 `--project` 同时用于两套安装的程序路径与摘要。普通入口仅从各自已固定摘要的安装锚点读取对应程序根，重新核对该程序快照和本安装的绑定。`--project` 继续指向受信生成器所用的程序。任一锚点或程序不符，整批配置不发布。原环境身份、连接组、认证和候选阶段选择继续按各自原门槛核对。

## R193 发布核验身份的安装入口

`verify-release-gateway` 只接纳安装策略中已登记的 `AUTOMATION`／`READ_ONLY` 身份。已有普通安装的默认自动化身份可写，不能替代。普通 HTTPS 新安装可由受信维护者从固定程序运行 `backend.app.infrastructure.environment_provision`，用 `--with-gateway-verifier` 明确登记一个依本环境 ID 固定的只读核验身份。实际凭据仍由受保护的独立配置提供，后端按原访问契约核对来源与写入限制。未选用该选项的安装继续使用原身份配置。已有安装可通过既有 `RECONFIGURE` 准备等价身份；恢复副本与独立候选继续沿各自入口。

## R195 在新切换以前核对网关复验角色

复核 V2.01 后端 4.11 的目标预检及 4.12.2 的原部署保全。已登记独立 HTTPS 连接组的普通目标，必须在其固定访问策略中具有一个可用于后续网关实测的只读自动化身份。准备发布、同结构程序回退、重配和恢复目标时检查即将采用的策略。管理端生成新目标观测时也须检查，避免旧版工具准备的目标在确认之前显示可用。新切换写原转换记录前再次检查，防止其他接续路径绕过检查。已经保全原转换事实的操作继续按原回执和到达状态核对，普通启动、无入口组的离线验证与独立候选沿现有入口。此项仅核验角色及保护记录，实际凭据、HTTPS 进程和客户端证据仍按原开放规则检查。

## R196 验证受保护的 Vite 接入

V2.01 后端 6.3.3—6.3.5 的 HMR 保持独立 HTTPS、精确 Origin、入口认证、凭据删除和原 API 直连。Linux 开发服务采用独立 Unix 套接字，变更仅涉及该节原回环 TCP 监听方式。固定 Node 和 Vite 使用目标环境自己的源码、依赖和缓存；Vite 不持有业务数据、认证材料和其他环境的套接字。角色与发布固定静态产物继续使用现有入口契约。

原型先验证固定 Vite 能经反向代理代理实际模块和同源 WSS，两个范围分别更新，不产生 TCP 监听。接入版本使用宿主受信账号拥有的、上级目录不可由开发身份写入的套接字，由 systemd 传给低权限 Vite 进程。这保证开发身份不能把共享入口的上游路径替换成另一个环境的套接字。入口仍只发布固定配置、已登记页面、必要开发模块及本环境 API。候选和固定发布配置拒绝开发上游。实际编辑、断开、拒绝直连及原固定静态站分离以原生联验证明。

### 普通环境的 Vite 启动参数

- 每套开发或集成工作区使用独立前端 UID。工作区由该 UID 持有，权限为 `0700`，独立 `npm ci` 产出本工作区的 `frontend/node_modules`。Vite 缓存另设工作区内的 `0700` 目录，位于 `frontend/` 之外。
- 宿主创建 root 控制的目录 `/srv/walle-vite/<environment_id>/`，权限为 `0755`。systemd 套接字使用 `ListenStream=/srv/walle-vite/<environment_id>/vite.sock`、`SocketUser=root`、`SocketGroup=<本环境入口连接组>`、`SocketMode=0660`、`RemoveOnStop=yes`。Vite 的 UID 无需加入该组。
- 对应服务使用独立 `User`／`Group` 与 `Sockets=<对应的.socket单元>`，设置独有 `HOME`／`TMPDIR` 及 `UMask=0077`。测试使用 `NoNewPrivileges=yes`、`RestrictAddressFamilies=AF_UNIX`。服务直接执行固定 Node，避免由 npm 转发导致套接字归属 PID 不一致。

```ini
ExecStart=/path/to/fixed/node /path/to/workspace/frontend/serve-isolated.mjs https://e-<environment_id>.walle-dev.test:9443 /srv/walle-vite/<environment_id>/vite.sock /path/to/workspace/vite-cache
```

- 在普通双站的原 `environment_gateway.py --site <anchor> <sha256>` 参数之外，为需启用开发模块的站点增加 `--vite-site <environment_id> <vite.sock 的绝对路径>`，其他站点保留自己的固定静态根。生成器校验宿主控制的套接字目录、原安装入口组和环境用途。停止时结束对应的 Vite 服务，再关闭对应的 systemd 套接字。
- 开发连接检查只通过已认证的 HMR 连接往返。连接超时或断开时，动态页面显示“开发连接异常”，保留页面内原业务和 API 入口。固定构建不注入该状态模块。
- Chromium 实测发现锁定 Vite 8.3.2 的客户端实际导入 `/node_modules/vite/dist/client/env.mjs`。开发入口增加此唯一精确依赖路径，普通固定入口及其他 `node_modules` 路径沿原规则。
