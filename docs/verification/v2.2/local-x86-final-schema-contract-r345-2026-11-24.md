# R345 最终固定程序与原 Schema 的结构核对

2026-11-24（香港时间），独立 `codex/2.2`，本机无网卡 Ubuntu x86_64、固定 Python 3.13.18／SQLite 3.54.1。对比 R325 原应用与 R344 最终应用的两个真实固定 Schema，使用同一固定运行包、同一 Schema 发布 ID 与各自真实程序字节。

- 原应用重新通过锁定入口 `runtime.py build-schema` 生成清单，摘要 `2639f06f41b13892bc2c78a9228d278665e11f74e10e88f2b388b1dee87aafdf`。R344 的实际最终清单摘要 `4a1572aa48a669cae755dd91207d45998f7ad53ef776a57f2109cb7e0075c552`。用发布现有 `checked_schema` 分别按自己的程序字节验证，两个包均通过且保留独立身份。
- 实际 `fresh.v1.sql` 和 `objects.v1.json` 逐字节相同，结构合同 SHA256 均为 `ed057e0ddadbcdbb47bd8e78c541cf009fd719c397ffe79579d3ae2684802fc3`。两份清单唯一变化是受绑定的 `tools/linux_runtime/serve_environment.py` 来源摘要。尝试用新程序验证原清单被拒绝，最终清单自身保持。
- `python run-guest.py r345a-schema disk-r344-final.qcow2 offline 285` 退出 0。早期一次夹具的异常类导入路径错误，按实际模块位置修正。确认的是本机两个真实构建的同结构前置资料，正式候选兼容回执与开放仍依赖实际集成交付和封存。
