# V2.0 Git本地配置白名单及固定Git向量验证

日期：2026-11-05。设计BE0.17-draft-17，7.7.1—.2；实施绑定独立保留pending，未自动合入正式设计。V2代码仍为28a7c9e后的未提交工作区。

## 实现与边界

新增infrastructure/git_local_config.py：config_source_sha256先限制原配置副本字节并拒绝嵌入NUL，返回原字节摘要；validate_local_config_output严格处理成功结束后的完整NUL输出，绑定真实object_format／bare及首期格式版本／files后端。限制字节与条目后才解码，不把缺失读取当空配置。

精确采用7.7.2允许键。布尔按首期标准文字／0／1／隐式形式处理；描述字段不用于执行。禁止include／includeIf、worktreeConfig、任意hook／fsmonitor／路径、credential、alias、filter／签名及未知键；重复结构键逐项匹配布局且版本冲突拒绝，不借最后值掩盖前值。输出仅LocalConfigFacts的输出SHA256／条目数／布局事实，不保存描述值、远端URL或个人身份；异常固定原因，无原键值。输出摘要与原文件摘要分开。

Git官方说明NUL记录及LF键值分隔和隐式布尔等规则；实际编码另用本项目固定2.56.0.windows.4验证，不以文档代替运行结果。[Git config官方文档](https://git-scm.com/docs/git-config)。后续部分浏览请求403，未以其他非官方资料推断兼容范围。

## 实际检查

项目Python3.13.5／Ruff0.17.3／固定SQLite3.54.1；quality_python及脱敏环境。真实Git仅在新建专属临时目录、自有KILL_ON_JOB_CLOSE Job内的独立测试worker执行，无网络／正常Git仓库／索引／引用访问。原生测试不更新Guard或系统策略。

- 初始配置／选择／路径／manifest四文件188通过，0.28秒（后续追加源字节专项1项）。
- 首次六文件扩展：243通过／真实Git向量1失败，3.80秒；独立worker不含项目sys.path，新增不必要的产品import导致ModuleNotFoundError。已移除worker产品import，使用独立字节／hashlib事实；产品验证仍在父进程调用。随后遗漏父测试导入NameError已补。
- 最终受影响两个文件test_git_local_config.py＋test_content_manifest_git_vectors.py：58通过，4.51秒；配置57项及完整真实Git向量1项。未将分次结果声称一次244项全过。
- 真实固定Git：原sha1／sha256新bare的config私有副本在非仓库cwd用config --file <copy> --no-includes --null --list解析；原源摘要与生产预检查核对、真实输出交生产白名单。另真实验证无等号core.bare输出、保留多行user.name值、--no-includes不读取已存在的include目标、禁止hooksPath。原blob／tree／commit写入、cat-file及确定交付payload两格式向量在同一真实检查中继续通过。
- 最终新模块lint、178个backend/app格式及git diff --check通过；db20-r7 source pin复核通过，新模块不在SOURCE_NAMES中，没有覆写历史发布资源。前端未再修改，目录批次492项／strict／format／构建不机械重跑。
- 既有httpx弃用警告保留。测试Job成员及worker结束，临时配置／JSON／Git库随专属根清理，无原始报告／日志残留。

## 未覆盖及下一步

本解析器没有生产执行Git或路径IO能力。原配置真实句柄／私有副本权限、仓库布局／锁／worktree检查、原指纹重验、受控环境与完整Git命令登记，以及原Operation调用方仍待实施；不能据此使Q20-GIT／runtime_admitted为true。真实Git向量使用普通测试宿主，不冒充认证Guard／SYSTEM／LPAC或整Task STOP。

正常用户数据／.env.local／服务／系统权限／网络规则没有变动；无付费请求。源码原子保存，测试资源不作常规产品数据或正式包。
