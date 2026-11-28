# WALL-E

WALL-E 是单用户需求工作台。用户可以围绕同一需求开展 AI 辅助讨论，生成、修订和审阅多份文档，并保留版本历史。

## 运行与架构

日常使用 V2.2。开发和集成环境都运行在 Mac 上的 Linux 虚拟机内，由 systemd 管理。Caddy 按 HTTPS 站点把请求转发到对应的后端。每套环境独立保存 SQLite 数据，并从同一个站点提供已构建的前端和 `/api/v1`。

前端使用 React、TypeScript 和 Milkdown，由 Vite 构建。后端使用 Python、FastAPI 和 Uvicorn。

在已配置的 Windows 工作站，双击项目目录下的 `output/v22-mac-access/打开 Mac WALL-E.cmd`，并在访问期间保持启动器运行。启动器通过 Mac 的 SSH 跳板连接 Linux 网关并打开两套环境。

## 从这里开始

- [V2.2 运行说明](docs/operations/v2.2/运行说明_V_2.2.md)提供两套环境的 HTTPS 入口、部署状态和服务核对步骤。
- [V2.2 实施进度](docs/project/v2.2/实现进度_V_2.2.md)记录接续位置和授权范围。[V2.2 需求实现映射](docs/traceability/v2.2/需求实现映射_V_2.2.md)记录能力、证据和剩余事项。
- [项目文档导航](docs/README.md)汇总各版本设计、决策、验证及历史档案。

历史资料见 [V2.0 设计](docs/design/v2.0/README.md)、[V2.0 数据库维护说明](docs/project/v2.0/数据库维护使用说明_V_2.0.md)、[V1.5 项目资料](docs/project/v1.5/README.md)和 [V1.0 收口资料](docs/project/v1.0/README.md)。
