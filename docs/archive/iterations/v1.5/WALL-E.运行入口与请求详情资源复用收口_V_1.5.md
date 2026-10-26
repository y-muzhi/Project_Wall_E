# WALL-E V1.5 运行入口与请求详情资源复用收口

2026-10-24。v15真实技术及26EV完成后进行非AI读取／运行配套收口，不修改已实测的模型Prompt、Schema、Wire、计数、profile、执行链或冻结资源，不需要重新请求供应方。

实际缺口：model_calls._collaboration_detail每次GET都创建ResourceCatalog，重复装载／核对整套资源，批量历史只读明显较慢；HTTP runtime已有冻结catalog却未传入。现由原API传runtime.catalog，get_model_call增加内部可选catalog参数，直接读取仍保留兼容默认。响应、保存内容、计数／预算及权限不变，GET不重编译或触发计数。

旧ai-service.py仍检查1.0 Function和context_projection_v1。现复用collaboration资源及正常CollaborationAdmission：默认离线只显示固定模型／release／预算，不读密钥／数据库或启服务；显式--start必须先有绝对已初始化schema150库及同release有效准入，之后才安全读凭证，配置该进程环境走原单worker入口。不初始化／迁移、导入证据或调用模型。运行说明提供新库、显式准入及开发前端入口；本轮不执行真实启动或用户库配置。

已合入正式BE的请求详情读取及资源／准入运行边界，属于非模型文字。当前BE SHA256=02acb5f3bf621ff2a10c362818529cc0f8bc5f5b4988cb3226336607fc1eead8；v15 manifest采用时BE9f7e6476…保留，模型源字节一致性再1项通过，不重建冻结资源。请求详情／HTTP及模拟启动7项50.64秒通过；补旧schema边界后启动3项27.60秒通过。25实际请求只读完全相等且不重载／编译／调用，原真实证据哈希不变。验证见startup-catalog-closeout-2026-10-24.md；当前源码3d5458ba…单独记录，真实执行时9cf0a135…原值保留。已重整运行说明，未做真实启动、导入用户库或生产部署；本迭代归档，不代替人工语义签字。
