# V1.5 新库与需求基础专项

- 日期：2026-10-22（Asia/Hong_Kong）；未提交工作区。
- 范围：独立schema 150、显式数据库路径、创建零文档／零运行、需求属性幂等及metadata_version、五态任意切换、需求详情摘要／按需discussion、旧初始化拒绝、complete／reactivate新属性语义。
- 环境：项目`.venv`，TemporaryDirectory／pytest tmp_path隔离SQLite，FastAPI进程内ASGI TestClient；没有开启监听服务、修改用户库或调用供应方。
- 命令：`.\.venv\Scripts\python.exe -m pytest backend/tests/requirements/test_v15_foundation.py -q -p no:cacheprovider`。
- 实际结果：9 passed，5.49秒。覆盖零文档零调用、初始消息及创建幂等、全部25种状态组合、同状态NO_CHANGE、重放／冲突／双并发版本、活动运行关闭不取消、创建及事件失败回滚、实际HTTP新契约／错误码、旧库原字节不变、schema摘要／结构检查。
- 首次运行8通过1失败：在途运行输入夹具用了晚于宿主UTC当前时刻的固定日期，触发事件时间不可倒退检查；改为该需求真实updated_at后通过。未放宽产品时间约束。
- TestClient显示现有Starlette对httpx适配的弃用提示，未为此变更锁文件。
- 新schema从零保留17张原职责表；历史001—004脚本不修改，不执行旧库迁移。多文档／Revision／批次／评论的新字段与约束已加入，但其业务入口仍需后续B3—B5接续验证，不能称全部存储路径完成。
- 当前前端尚未同步新详情／状态／创建契约，不能声明页面可用；旧版后端专项夹具及未适配能力仍需按新设计更新，不以这9项通过替代全量回归。
- 临时库和锁文件由测试临时目录清理；只留本文Markdown。未执行浏览器、真实Tokenization／Chat、用户服务更新或Git写操作。
