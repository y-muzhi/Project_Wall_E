# 后台可执行包准备（2026-11-13）

本轮香港16:35:30开始，目标18:35:30。按[独立迭代](../../iterations/pending/v2.0/WALL-E.受保护后台离线构建与清单准备迭代V1_V_2.0.md)，仅本地准备／隔离验证，不安装服务、改系统ACL／WFP、开启ready、写正常库或Git目标，不调用模型／计数。

## 实现与边界

backend/frozen_backend_entry.py复用backend.app.__main__.main；默认127.0.0.1:8000、单worker、无reload。显式--port只接受整数1024—65535，不选择端口、不扩大监听地址。--verify-runtime核对固定SQLite3.54.1、Schema200 release、ResourceCatalog及固定Git完整包，不打开业务库或连接Guard。

tools/windows_backend_package.py和tools/build-windows-backend.py按固定Python3.13.5／项目运行锁与独立7项构建锁，从原LockedFileSource读取FileID和完整SHA，复制独占源快照；实际构建专用onedir walle-backend.exe，不使用onefile或外部Python代理。临时源／spec／cache／依赖／日志退出即清理；官方PyPI固定wheel按requirements-build.lock验证，只装临时目录，未改项目venv／全局环境。

实际EXE的--verify-runtime通过后，重新核对原源码集合／FileID／全SHA，再严格生成原BACKEND20-PROTECTED-1规范清单，校验实际PE、完整文件目录、隐藏流及限额，无覆盖原子发布新目录。准备包在backend/distributions/windows；不是测试报告，不受output临时报告清理。未设置受保护ACL，未安装／注册SYSTEM Guard，未生成正式OS准入。

新增--build-frontend使用原锁定Node、tsc --noEmit与Vite，在本轮临时dist编译当前前端；编译前后及发布前核对完整前端源集合／FileID／SHA，将源摘要纳入构建输入摘要。未覆盖frontend/dist。显式--frontend-dist仅用于已有产物输入，二者互斥，不能把已有dist当当前源码。

## 实际失败和修复

- program_ref含冒号被原格式拒绝；改为原16—128位ASCII字母／数字／下划线／连字符，不改校验器。
- 清空环境导致PyInstaller无法解析home；改为本轮临时USERPROFILE／APPDATA／LOCALAPPDATA。
- 实际EXE首次探针因_ctypes缺ffi-8.dll失败；构建子进程显式加入当前固定解释器Library/bin查找路径后恢复，不改全局PATH／依赖版本。
- 默认8000被后来启动的python PID251396占用；检测后未访问或停止该进程。新增显式端口仅为原正常入口能力，测试用独立空闲端口并逐次核对原Popen监听PID。
- 旧frontend/dist构建包虽HTTP字节校验通过，IAB中只有“需求工作台”导航。当前源码有三个入口，因此新增当前前端构建选项，未将旧页面误报为V2.0完成。
- 当前前端真实页面发现任务目录“测试计划与资源”按钮把React事件传给可选plan编号，被原校验拒绝。配置页同类入口实际正常；修复task-list.tsx按钮为无参调用，保留路由正整数校验，正在重建复查。

以上失败均未产生安装／准入；失败临时目录和原自有进程均按所有权收尾。

## 已完成检查

- 受影响新生产模块Ruff lint通过；backend/app、backend/runtime_guard、新入口及两构建工具Ruff format共508文件通过。
- frontend npm run format:check通过，包括本轮按钮修复。
- 原构建准备4项／1.57秒、端口／Schema来源／组合26项／24.37秒通过；最终构建准备与端口联合13项／1.59秒通过。范围有重叠，不累计为独立用例总数。合成PE只用于结构负例，不冒充实际构建。
- Schema来源更新为db20-r49，manifest SHA256 0bbee789537272e79070cec33e0c2fd4646bfbbb61545bde9592e4fd17c2e194。__main__变化触发来源更新；r48与r49的objects／fresh／upgrade三资源逐字节一致，没有维护正常数据库。
- 实际r48准备包prepared-20261113-1748：1785成员／264077590字节，manifest SHA256 574f5507333c929a52e70848193ef8cb1b52eb6e0847f930dbefb613a8839b62，原EXE运行探针通过。
- 实际r49准备包prepared-20261113-1758：1789成员／264977023字节，manifest SHA256 a15a7f37d003f32413689a07a75e75679fec1b8703334e0d76c000ad8f172f14；独立新库／随机端口的首页、JS原字节与3个API共5项通过。其旧前端不推荐作为当前UI。
- 当前前端准备包prepared-20261113-1819-current-ui：manifest SHA256 2477acc2793bc2326ed82fb515be95d6bf049092685f204c5b3b5dc7d446b59b。真实EXE隔离HTTP5项通过；IAB实际三个导航可达，代码开发提示选择需求／文档，Testing列表空态／分页禁用原因、配置空列表／未选版本禁用、计划目录空态／未选计划均已观察。任务目录计划按钮失败单独记录，未抹去。
- CLI浏览器显式原厂Chrome／独占profile／原Job启动后提示DevTools要求非默认数据目录并退出。没有关闭浏览器保护或修改用户策略，不算页面通过。后续IAB普通页面证据与正式CHECK_DRIVER隔离浏览器证据分开。
- 隔离HTTP入口每次请求核对实际EXE原PID及镜像，首页和脚本SHA与包清单一致；fresh库llm_uses=0、code_tasks=0，浏览后复核仍0。已结束的自有服务及临时库自动清理。

本记录不证明完整Chromium CHECK_DRIVER、受保护安装、SYSTEM／WFP、真实供应方，或完整Coding明确修复／报告接收／Git交付验收。最终修复后包与浏览器复核结果在下方追加。

## 18:27最终修复包及实际页面

prepared-20261113-1826-fixed-ui实际完整构建成功，原EXE运行探针通过；manifest SHA256 81c33f1bc2c0c02c1bea7bf8f515bbccb83208ca24e9d8feb1bc72960c8612e9，构建输入摘要5dfc261e7a91d3df0f6e17b2f2c35d26ae32b3de510fb6517c700a7b9acc49a3，1789成员／265664673字节。构建过程完成tsc --noEmit及Vite当前源码编译，不使用旧dist。

使用v20_frozen_backend_http_worker.py、独占临时SQLite库、127.0.0.1:57526和原Popen镜像／PID，首页SHA、实际脚本SHA、requirements／code-execution-profiles／code-configuration-options共5项通过。IAB新建后台标签实际点击“测试验收”→任务目录“测试计划与资源”，路由成为/testing/plans，标题及计划目录、空列表、无选中计划、空名称创建禁用原因均实际显示，原故障已修复。没有输入／提交业务内容或触发模型；标签已关闭，截图只在内存观察，不保存文件。服务和临时库随后按原所有权收尾，用户8000服务未动。

## 18:32最终来源校验版

构建来源ADS负例最初5 passed／1 failed，确认frontend_sources未检查隐藏流；补用原require_default_data_stream后6 passed／1.68秒，未改共享读取器。最终包backend/distributions/windows/prepared-20261113-1830-source-checked成功：manifest SHA256 5145ff98b55551094f5804f813724bef1c27e75302611fe2ee471a86b3eb7e1f，来源摘要138e3bfd48e688868629a246bbdf9222bc2d39ddc44906bb77a16cf911e1c4c6，1789成员／265664762字节；实际EXE资源探针及独立随机端口HTTP5项再次通过。构建工具最终Ruff lint及专项格式通过。

额外只读复核最终实际每个文件的长度／SHA与manifest完全一致，实际文件集合等于manifest成员加自身；最终前端全部原字节与18:27 IAB修复复查包一致。当前源码集合／FileID／全SHA再次计算的来源摘要与构建输出完全一致。该复核无输出报告文件、业务库或服务变更。未重新宣称IAB在最终端口执行；页面证据来自18:27包，最终前端字节相同证据单独明确。
