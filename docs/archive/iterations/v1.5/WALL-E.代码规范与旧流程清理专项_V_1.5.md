# M15-CODE-01代码规范与旧流程清理

2026-10-30；H11用户授权当前代码整理、提前规则约束和删除无必要旧流程，本轮实施及必要检查完成。禁止真实模型、用户数据／服务变更及提交推送；现有H08／H10改动保留。

批次：A锁定格式规则及AGENTS开发约束→B当前前后端源码排版与等价核对→C旧流程生产／工具／测试／文档依赖核对与删除→D相关离线回归及文档同步。格式检查不冒充架构质量或全部旧代码删除。

已核对生产service→worker→orchestrator，仅collaboration_v1可执行；旧INITIALIZE confirmed_response没有生产调用，当前card_commands→fact_confirmation已替代。删除旧实现及专属测试，去除历史输出测试中的无效mock，修正正式BE原实现引用。framing_probe仍有技术观测工具调用；local_credentials为启动工具需要；旧资源／结构仍被当前校验和保存快照投影依赖，不凭年代删除。

前端Prettier3.9.10锁定，src范围统一排版，format步骤接入统一检查；8自检、格式、420前端、类型、临时构建通过，报告quality-gate-2026-10-30-202632-169994.md。Python125文件AST一致；8自检、双格式及33项当前后端专项通过。无用户服务操作。

正式FE／BE1.3加入维护要求，BE卡片事务定位改为card_commands／fact_confirmation。没有增加业务实体、改协议或改变用户行为；未将所有历史文件认定无用。实际证据见[H11验证](../../../verification/v1.5/h11-code-maintenance-2026-10-30.md)。
