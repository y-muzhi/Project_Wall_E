# R411 持久开发与集成工作区的依赖和构建

2026-11-24（香港时间）。Windows 两持久独立仓库 `output/v22-dev-isolated` 与 `output/v22-integration-isolated`，分别为 `codex/2.2` 和 `codex/2.2-integration`。集成 HEAD `deacba8a9545122f35a2f85c125a354205e06461`。Node 24.15.0，两个前端锁文件 SHA256 均为 `cbc9f8d37f0c827937140a780ced8790b1694707dd174d8ec0df8fc8b3c09f8c`。

- 集成侧原先无本地依赖根。使用相同锁文件下已安装的本机依赖制作独立副本。在同一文件系统的专属临时目录复制并逐文件复核 8,402 项，字节摘要相等、NTFS 文件身份各不相同、无重解析点；随后一次放入集成自己的 `frontend/node_modules`。两侧 `import.meta.resolve` 实际核对 TypeScript、Vite、React、Milkdown 和 Prettier 均解析自各自独立目录。保留该依赖目录供明确集成交付使用。
- 执行集成侧本地 `tsc --noEmit`，真实普通和管理 Vite 构建分别生成 120 项和 3 项。随后开发侧独立重建，普通和管理也分别生成 120 项、3 项。对各输出相对路径及字节摘要排序后测得：

| 输出 | 集成基线 | 开发工作区 |
| --- | --- | --- |
| 普通 | `02f69376c6813a3fbc7b2956a1c49afb52cb21bc73c8220c8126c71239ab40ad` | `11dd10bcc41fc4d31afc93acd62ed5a770c34c1e77fa5f720c660bfbd0495c38` |
| 管理 | `17d5e6532a20e06224968fa5df978bbf3092bf5b674ac16fba525e4ac1aa3935` | `159a64578f1ae6b90ebd6ace818e5866ce5d392554763d0447414697d9d9e052` |

- 按同一独立集成目录执行 `node --test tests/*.test.mjs`，603 项基线用例及锁定 Prettier 格式检查通过。跨语言规范检查通过显式 `WALLE_OFFLINE_TEST_PYTHON` 使用已锁定解释器，源码仍从当前独立集成目录读取。
- 开发重建期间集成两份输出摘要保持。普通构建仍有既有大包提示。依赖准备与本机构建未启动服务。两份临时构建目录按原归属清理，集成跟踪区仍为干净基线。正式候选仍按最新源码的明确集成交付重新构建。
