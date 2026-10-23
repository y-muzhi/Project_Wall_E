# V1.5局部修订及v10资源离线检查

2026-10-22；Windows／项目.venv；工作区未提交。

- 新resources/v10由正式设计ec48d4b36869d11b7fa8032e9b6b60ad2b80e0021a47398d93b1106fb9db8e9c生成21项资源，Prompt common v2／release v2。manifest SHA256 07e4364b97c980ba1b3e5dbc8f17b75ab1873eded1a85ddbe1b4df352ddfa755；release SHA256 51682604bd1665e2060238ac72373a105c11ea05d2a0008d4d835f40f9bf026e。默认ResourceCatalog改装载v10；同批唯一key可省version，显式版本仍严格核实。不把不同digest复用为同一Prompt版本。
- `python -m pytest backend/tests/infrastructure/test_collaboration_resources.py backend/tests/guide/test_v15_execution.py -q -p no:cacheprovider`：22 passed／83.23秒。89类型闭包、摘要、确定字节、准入阻断、实际单轮执行与局部稿／越权返回校验；只用显式离线替身。
- `python -m pytest backend/tests/guide/test_v15_local_revision.py -q -p no:cacheprovider -x`：4 passed／38.47秒。SECTION局部新增，范围外重复内容身份不变；Unicode SELECTION精确改变／范围外拒绝；BLOCK省略结尾换行仍NO_CHANGE。
- v9 manifest仍为daf7ee47c3d4aab4e186f29c195be10e6e17795db5299dae9b3727cedd93ce8c，未覆盖。v10仍OFFLINE_READY，真实调度在计数／Chat前阻断，无真实准入证据。
- 新版资源影响共享上下文和执行基础，18个V1.5专项文件扩大联合正在运行，待实际结果。前端卡片selectable scope复用原编辑器scope证明，新稿类型及结构已接；card草稿schema2保存execution_selection，6项卡片与批次／请求共26项通过／317.46毫秒；完整tsc通过，最新UI尚待临时构建。
- 所有测试使用隔离TemporaryDirectory并清理，未写用户库、未启停服务、未执行Git写入。未执行浏览器与真实供应方，不把离线结果作为产品验收。
