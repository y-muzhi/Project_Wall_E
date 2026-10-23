# V1.5 工作台、创建及人工状态前端专项

- 日期：2026-10-22；当前未提交工作树；正式前后端设计1.0／EFFECTIVE。沿用现有组件和ApiAction，无服务启停或真实调用。
- 创建只含标题／类型／初始想法，201严格解码初始消息和空文档；不提交GuideRun。列表五态；原筛选、分页、迟到响应保护保留。工作台历史schema2及walle:v1.5键不迁移旧缓存。
- Requirement公共字段切至五态／属性版本／讨论版本／原始消息／closed_at；移除旧初始化字段。页头五态选择直接发送带metadata版本和幂等键的PATCH，不增加确认门槛；状态与工作占用分开。标题未知结果保留并核实原动作；新增三类版本冲突的安全解析。
- 命令（cwd frontend）：`node --test tests/requirements.test.mjs tests/v15-foundation.test.mjs tests/workbench-history.test.mjs tests/workbench-pause.test.mjs`：17 passed，304.11毫秒。包含真实ApiClient wire／键、创建与标题UNKNOWN、状态在占用期间切换、Unicode边界、查询竞争及历史恢复。
- `node node_modules/typescript/bin/tsc --noEmit`：通过，包含src与tests/browser；旧诊断创建／初始化行为同步为新创建与状态入口，未运行浏览器诊断。
- 生产构建：Python TemporaryDirectory包裹Node执行Vite `build --outDir <临时目录>`，1240模块，540毫秒；退出清理目录，没有覆盖frontend/dist。已有大chunk提示仍在，未改构建阈值或为本单元增依赖。
- 首次专项中工作台历史夹具仍传ACTIVE导致1项失败，已改新五态，并为新缓存schema／namespace同步覆盖；最终17项全通过。
- 范围限制：本记录仅前端基础及现有构建。RequirementDetail／多文档正文／人工编辑回执／历史与评论API尚未完成前端接入；当前详情仍有必需CURRENT的旧假设，不能宣称创建到详情全流程或V1.5交互验收。卡片与AI仍待后续批次；无真实供应方／计数／浏览器证据。
