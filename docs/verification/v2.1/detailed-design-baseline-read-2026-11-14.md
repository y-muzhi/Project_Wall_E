# V2.1详细设计的来源核对

日期：2026-11-13—14（Asia/Hong_Kong）。工作区codex/v2.1-design-review，HEAD21651c338ef3546c39a65526ed53c24653f30c77。本轮仅文件静态阅读及详细文档输出，无产品执行。

当前工作区与原工作区V2.0未提交实现不同，未将外部代码复制到本工作区。下列SHA256是本次读取文件原字节的来源定位，不证明整库兼容或供应商当前能力。已读范围按表说明；全部V2.0生产调用、完整资源图、业务数据及服务现场未核实。

原工作区：C:/Users/羊牧之/Documents/ChatGPT/Project_Wall_E 2。该目录的Git HEAD查询被文件访问边界拒绝（Permission denied），没有升级权限或改动原目录；可读文件原字节已独立取得摘要。因此没有编造原工作区的准确提交／未提交清单，该项保留为实施前输入。此限制不妨碍本轮文档输出。

| 来源域 | 文件（相对相应根） | 实际用途／已读边界 | SHA256 |
| --- | --- | --- | --- |
| 本工作区 | AGENTS.md | 本轮约定及授权／原子保存／静态证据 | `2d6cfcabe83fdf77354c1a8c1e11d04ab562c8ebefd4a35c0624ced42973e7ec` |
| 本工作区 | docs/templates/统一需求规格说明_完整模板_重构版.md | 完整模板八章及条件条目，分段读取 | `7e73b764207aac74f43b70996c2b84ce68e8233f2ccf161a95f613e653e0bc66` |
| 本工作区 | docs/iterations/pending/v2.1/WALL-E.大纲设计基线_V_2.1.md | 完整当前0.12及76项预期、8来源清单 | `3774e919a16cd09e18a548ee06227836f73cddea64fe1c89ea516caa441ff6a1` |
| 本工作区 | backend/app/guide/collaboration_context.py | 实际Wire八根、system职责、八段计数及compiler真实职责 | `8afbc177d3b4502ffb0e915e02938451fd1990f4dbca1fde53c2d2be0a07b18b` |
| 本工作区 | backend/app/guide/contracts.py | 原创建运行／正式回答／状态结构相关范围 | `08b8b1ba18fb60ca5f6034da8c289a273409a2689144f710e37094dd0c8bdd4b` |
| 本工作区 | backend/app/guide/http_models.py | 原HTTP九个创建字段／202与RunAccepted | `691eb42227f45f122c41d88fb109dd798e3e404d2d9693b1dd8f66aa26587034` |
| 本工作区 | backend/app/messages/http_models.py | 原responses五字段、状态分派 | `d78bcc1eec545a905eea0619c071f20a904af8667499be2b8fd47c519c3c4466` |
| 本工作区 | backend/app/messages/api.py | 原conversation-messages/{id}/responses实际路径 | `3f5ad5268e6cb39b38ce222aa8da8fb245844a5023b45a0d75cf62bd90a203f6` |
| 本工作区 | backend/app/requirements/api.py | 原GET／PATCH实际分派 | `488210776cf608ee5dac05c08c41cb5677566bfc34e1e2e90ef845ca82cb80d2` |
| 本工作区 | backend/app/documents/content.py | 真实提交来源／事务入口及新增CARD_RESPONSE缺口 | `0e7ae96fdc530f813c48e922529e6d8b83530a38f1f27bb38be1c3d0a780f697` |
| 本工作区 | backend/app/shared/http_boundary.py | 实际success/error封装、meta.pagination及8MiB边界 | `5a993c6d5df16a36a5b0e59bbddf84d89ed5419e825f7d90f7067523949e4891` |
| 本工作区 | backend/app/shared/http_errors.py | 安全错误投影、现有枚举与新增登记边界 | `f363cf5e030b2f2d79ad312992f51fc1b52b8a5be4edc4271394b6b67dc42e7f` |
| 本工作区 | frontend/package.json | 仓库实际锁定声明；未安装或联网验证 | `c71b43d1bd463951a79be43bb385d831e2af970e118e893084f389daa64a9f08` |
| 本工作区 | frontend/src/api/client.ts | PreparedCommand WeakMap、原key／body及未知响应处理 | `a2498b3b5397ebbb42e93a4958e16c20b2a8cf9b3e67c5071dd9e9d6cfef4a28` |
| 本工作区 | frontend/src/guide/composer-drafts.ts | 原sessionStorage输入键与schema1 | `6aa37e0ecee979b2c5826b3ea52a5d1126ce012099ea38b6165462184341d67d` |
| 本工作区 | frontend/src/guide/card-drafts.ts | 原sessionStorage卡答案键与schema2 | `937e9b7d6e4ac2cda728fc6b974e4a91e57c91f3cc11fb43013648658ec27a8d` |
| 原工作区只读 | docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md | 0.17-draft-17，相关共同对象／数据／事务／历史边界 | `1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37` |
| 原工作区只读 | docs/design/v2.0/WALL-E.前端设计文档_V_2.0.md | 0.16-draft-16，相关界面／恢复及既有模块边界 | `38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7` |
| 原工作区只读 | backend/app/infrastructure/schemas/v2_0/db20-r48/fresh.v1.sql | 完整SQL文件定位，重点核对requirement_documents／audit／idempotency与外键约束 | `9da3375bcaed99e9b492f4fda04119eef78dcc5784c2b5daf13ac118f28957ad` |
| 原工作区只读 | backend/app/infrastructure/schema_v20_state.py | Schema200与结构来源／状态校验 | `67df9a6094f7f4384da5bada8350130caefcc63ef9972226be6b323859ea37ea` |
| 原工作区只读 | backend/app/infrastructure/requirement_repository.py | 原文档根及讨论持久化接口 | `d166877179a6bd0459cbbf299a7c98b797d371089190c6a85498bddfaa03683f` |
| 原工作区只读 | backend/app/documents/content.py | V2.0原提交入口及复用差异 | `0e7ae96fdc530f813c48e922529e6d8b83530a38f1f27bb38be1c3d0a780f697` |
| 原工作区只读 | backend/app/requirements/api.py | V2.0原需求HTTP入口 | `488210776cf608ee5dac05c08c41cb5677566bfc34e1e2e90ef845ca82cb80d2` |
| 原工作区只读 | frontend/src/api/client.ts | V2.0现有传输／命令职责，未全量审查 | `6778e9c737210ae5d24ae76d9305f440b87fa1c5ee770c8559f8151e5c76f795` |
| 原工作区只读 | frontend/src/code-tasks/command-recovery-store.ts | 单IndexedDB名称／DB版本1／原两仓库／事务send gate／认领关键范围 | `7a7849439ded009488f392de069a375750949719aef7d02f4c2ddcff86cb07ce` |
| 原工作区只读 | frontend/src/code-tasks/command-recovery-model.ts | 原记录版本4、100条／128MiB／64KiB及严格类型相关范围 | `8ba4e1d7f21dc734964b08a814b66290a9a2ddbad27e4ca10ebcd67b096934c9` |

实际读出后修正了新规格中的路径、原responses字段、创建运行字段、HTTP success/error封装和meta.pagination、Wire八根／计数八段、RETURN_FROM_BRANCH动作及enter_after_resume字段；CARD_RESPONSE仍明确为新增目标，未冒充已有支持。未采用v5探索Schema，没有修改旧Schema、冻结资源、正式模板或前后端产品代码。

本轮工具没有访问业务SQLite、模型／计数端点或服务端口。实际源Schema200/db20-r48定位仅服务目标设计；完整目标DDL、发布编号、升级工具及演练尚未生成或执行。详细设计为[后端](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md)与[前端](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md)，静态交付见[输出核对](detailed-design-output-2026-11-14.md)。
