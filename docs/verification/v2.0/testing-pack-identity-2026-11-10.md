# 独立 Testing 测试包草稿与目录

2026-11-10 香港时间 12:58 接续，Git master 28a7c9e、前后端设计摘要见实现进度，Schema200 沿用 db20-r35。BND-TEST-API-15—17 按已发布计划版本、原依据、空对象和原命令键登记 DRAFT，按原所属读回，未封存／父计划撤销分别展示。目录和详情省略私有 content_ref，未形成的封存及验证字段为 null。

使用真实 ASGI 与私有 Schema200，运行 `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_pack_api.py backend/tests/test_testing_plan_api.py backend/tests/infrastructure/test_v20_command_http.py backend/tests/infrastructure/test_v20_published_schema.py`，13 项通过。覆盖父版本缺失／草稿／撤销、成功和拒绝原回执、跨路径、并发单调版本、非法字段及真实空页，核对没有 Verification、独立任务、检查配置或模型副作用。Ruff 受影响模块及格式通过。

前端接入 /testing/plans 的包分区和严格祖先，Chrome 联合专项正在核对。测试包封存、验证及实际运行资格分别接续。
