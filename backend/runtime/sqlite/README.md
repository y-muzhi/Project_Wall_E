# 固定SQLite运行库

V2数据库构建、维护及应用启动使用项目内独立Windows x64 SQLite 3.54.1，原Python与系统库不替换。原始官方ZIP、DLL和DEF字节保留在3.54.1/win-x64，来源与SHA3／SHA256固定于manifest.json。官方[下载页](https://www.sqlite.org/download.html)公布归档SHA3；最低版本所需的WAL修复见[3.51.3说明](https://www.sqlite.org/releaselog/3_51_3.html)。

显式入口：`.venv/Scripts/python.exe -B tools/python-v20.py --probe`；离线专项在该入口后运行tools/quality_python.py。先激活再导入sqlite3；已有其他库绑定时拒绝，不静默回退。该包存在或探针通过不表示Schema200、维护窗口、用户库升级、Windows执行器或模型已准入。
