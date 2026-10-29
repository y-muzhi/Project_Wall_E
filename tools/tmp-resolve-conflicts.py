"""Resolve merge conflicts: keep local restructured docs, fold in the remote
commit's (aabfe478) additions. Remote blocks are taken verbatim from git blobs."""
import subprocess

REMOTE = 'aabfe478d8e4e50d341a4f961ecd6be15e4e7931'


def blob(sha, path):
    return subprocess.run(['git', 'show', '%s:%s' % (sha, path)],
                          capture_output=True, check=True).stdout.decode('utf-8')


def write(path, text):
    data = text.encode('utf-8')
    if '\r\n' in text:
        data = text.replace('\n', '\r\n').encode('utf-8')
    with open(path, 'wb') as f:
        f.write(data)
    print('resolved:', path)


# --- 1. pending/v1.5/README.md: insert remote line after local 2026-10-29 line
p = 'docs/iterations/pending/v1.5/README.md'
local = subprocess.run(['git', 'show', 'HEAD:' + p],
                       capture_output=True, check=True).stdout.decode('utf-8')
remote = blob(REMOTE, p)
remote_line = [l for l in remote.split('\n')
               if l.startswith('2026-10-29新增[公共确认按钮')][0]
anchor = '[长文档出稿专项](../../../archive/iterations/v1.5/WALL-E.长文档出稿专项_V_1.5.md)已按正式设计职责合入并归档'
assert anchor in local
local = local.replace(anchor + '\n', anchor + '\n\n' + remote_line + '\n', 1)
write(p, local)

# --- 2. 实现进度: append remote M15-CONFIRM-01 section at end (after H06)
p = 'docs/project/v1.5/实现进度_V_1.5.md'
local = subprocess.run(['git', 'show', 'HEAD:' + p],
                       capture_output=True, check=True).stdout.decode('utf-8')
remote = blob(REMOTE, p)
start = remote.index('## 当前断点（2026-10-29，M15-CONFIRM-01')
end = remote.index('## 当前同步（2026-10-27')
block = remote[start:end].rstrip('\n') + '\n'
assert 'M15-CONFIRM-01' not in local
local = local.rstrip('\n') + '\n\n' + block
write(p, local)

# --- 3. 需求实现映射: add remote mapping row to the main table
p = 'docs/traceability/v1.5/需求实现映射_V_1.5.md'
local = subprocess.run(['git', 'show', 'HEAD:' + p],
                       capture_output=True, check=True).stdout.decode('utf-8')
row = ('| 2026-10-29截图／M15-CONFIRM-01／BND-CONFIRM | 公共按钮文字居中、加载不跳动、'
       '交互同色系、所有声明复用 | shared/styles.css；Confirmation10处声明及创建需求 | '
       '[确认按钮检查](../../verification/v1.5/confirmation-buttons-2026-10-29.md)：'
       '类型／临时构建／8相关文件／隔离真实组件 | 代码与组件验证完成 | '
       '需求表单Python联测未通过，正式设计待归并，逐处业务链未执行 |\n')
assert 'M15-CONFIRM-01' not in local
sep = '| --- | --- | --- | --- | --- | --- |\n'
assert sep in local
local = local.replace(sep, sep + row, 1)
write(p, local)

# --- 4. verification/v1.5/README.md: insert remote entry after H06 entry
p = 'docs/verification/v1.5/README.md'
raw = subprocess.run(['git', 'show', 'HEAD:' + p],
                     capture_output=True, check=True).stdout  # keep CRLF bytes
local = raw.decode('utf-8')
assert '\r\n' in local
remote = blob(REMOTE, p)
entry = [l for l in remote.split('\n')
         if l.startswith('- [公共确认按钮对齐及交互配色]')][0]
anchor = '- [H06长文档出稿专项](h06-long-document-2026-10-29.md)'
assert anchor in local
local = local.replace(anchor + '\r\n', anchor + '\r\n\r\n' + entry + '\r\n', 1)
write(p, local)

# --- 5. 实施计划: keep local version (breakpoint prose lives in 实现进度)
p = 'docs/project/v1.5/实施计划_V_1.5.md'
subprocess.run(['git', 'checkout', '--ours', '--', p], check=True)
print('resolved (ours):', p)
