"""Reviewable v2 candidate only; never activate or mutate signed v1 bytes."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'backend/resources/v1'
TARGET=ROOT/'docs/proposals/resources-v2'
POLICY=ROOT/'docs/proposals/output-evidence-equivalence-v1.md'
card_rule='''
补充闭合协议：卡片分支message必须精确等于下述card_text，不用摘要替代、不在接收时修复。每卡第一行“卡片：”加card_key的JSON字符串；随后按question/context/card_type/required/selection_rule/custom_answer顺序各一行“字段名：”加字段紧凑JSON值；随后按原options顺序各一行“选项：”加按option_key,label,description,impact,risks顺序构造的完整紧凑JSON对象；再一行“建议（尚未选择）：”加完整recommendation或null的紧凑JSON；最后related_spec_context每条一行“相关需求原文：”加按block_id,content_snapshot顺序构造的紧凑JSON对象，没有条目则一行“相关需求原文：[]”。JSON保留Unicode，按JSON规则转义，冒号/逗号后无额外空白；required等为JSON布尔值。单卡各行用LF连接，卡片间恰一空行，末尾无LF。所有文本和字段完整展开，不能截断；整体须满足message既有容量。每条related_spec_context.block_id必须是实际读取区块，content_snapshot逐字等于完整原Markdown。推荐不是用户选择。
'''
fact_rule='''
INITIALIZE的事实采用只接受完整确认声明证明；短引用、包含关系、疑问、条件、助手推荐或自行拼出的肯定句不能证明。程序按真实当前目标与候选构造如下声明（LF行分隔，无末尾附加LF）：“确认事实变更”、 “目标区块：{block_id}”、 “章节：{完整章节路径JSON字符串数组}”、 “操作：{替换区块|在区块前插入|在区块后插入|删除区块|替换表格行}”、 “原文：”、完整old Markdown、 “确认的新正文：”、完整新Markdown；删除的新正文固定“（删除，无新正文）”。表格行的操作行后必须插入“原表格：”、完整原表格、“行选择：{实际selector紧凑JSON}”；新正文为完整cells的紧凑JSON字符串数组。比较仅采用SHR-TEXT的换行及外侧空白规范化，补丁自身原文继续逐字核对，不改候选字节。
证据须来自本次真实读取的USER TEXT整条content恰等于声明；或已实际提交的USER CARD_RESPONSE对原CONFIRM卡片选择confirm。该原卡question恰为声明再加“\\n是否确认以上事实和变更写入需求？”，两个选项依次confirm/“确认以上事实和变更”、defer/“尚未确认”，无自定义、无推荐，min=max=1，related_spec_context恰一个实际目标完整区块快照；正式答案选confirm/未跳过/无自定义且原文和目标匹配。推荐、defer或跳过不是确认。USER TEXT的一条evidence引用完整声明。CARD_RESPONSE的evidence引用完整实际摘要按Unicode码点每10000字符分割的全部连续片段，同message_id/原顺序/最多10条，拼回逐字完整，不能任选关键词/缺片/乱序；每Patch须另精确匹配实际confirm原卡声明，可引用同组摘要证明其中不同已确认卡片的各自Patch。未有证明时confirmed_fact_patches=[]，可生成上述完整确认卡片提问；不得自行肯定。确认声明超卡片/证据既有容量时询问更小事实项，不截断冒称完整。所有五Patch继续服从实际Scope/原文/组合及锁定结构规则。
'''

files={}
for path in SOURCE.rglob('*'):
    if not path.is_file() or path.name=='manifest.json':continue
    relative=path.relative_to(SOURCE).as_posix();content=path.read_bytes()
    if relative=='functions.v1.json':
        value=json.loads(content);value['proposal']=True
        for entry in value['functions']:
            entry['version']='v2';entry['prompt']=entry['prompt'].replace('@v1','@v2');entry['context_template']=entry['context_template'].replace('@v1','@v2')
        relative='functions.v2.json';content=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    elif relative.startswith('contexts/'):
        value=json.loads(content);value['prompt']=value['prompt'].replace('@v1','@v2')
        relative=relative.replace('.v1.json','.v2.json');content=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    elif relative.startswith('prompts/'):
        text=content.decode('utf-8').replace('@v1\n','@v2\n',1)
        context=path.stem.split('.')[0].replace('INITIALIZE_REQUIREMENT','INITIALIZE').replace('ANSWER_REQUIREMENT','ASK').replace('REVIEW_REQUIREMENT','REVIEW').replace('MODIFY_REQUIREMENT','MODIFY')+'_CONTEXT'
        text=text.replace(context+'@v1',context+'@v2')
        text=text.rstrip()+'\n'+card_rule+(fact_rule if path.name.startswith('INITIALIZE_') else '')
        relative=relative.replace('.v1.md','.v2.md');content=text.encode()
    elif relative=='BUSINESS-VALIDATION.md':
        content=content+b'\n\n'+b'Version v2 candidate: OUTPUT-EVIDENCE-EQUIVALENCE.v1.md is an additional mandatory program gate; status remains PROPOSED.\n'
    files[relative]=content
files['OUTPUT-EVIDENCE-EQUIVALENCE.v1.md']=POLICY.read_bytes()
entries=[{'path':name,'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)} for name,content in sorted(files.items())]
manifest={'schema_version':1,'status':'PROPOSED','base_manifest_sha256':hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest(),'files':entries}
files['manifest.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
if TARGET.exists():
    actual={path.relative_to(TARGET).as_posix():path.read_bytes() for path in TARGET.rglob('*') if path.is_file()}
    if actual!=files:
        if sys.argv[1:]!=['--refresh-unapproved'] or (ROOT/'docs/output-evidence-adoption-v2.json').exists():
            raise RuntimeError('Existing candidate differs; review it instead of silently overwriting')
        prior=json.loads(actual['manifest.json'])
        if prior['status']!='PROPOSED' or set(actual)!=set(files) or any(len(actual[entry['path']])!=entry['bytes'] or hashlib.sha256(actual[entry['path']]).hexdigest()!=entry['sha256'] for entry in prior['files']):
            raise RuntimeError('Only the complete intact owned unapproved candidate can be revised')
        for name,content in files.items():
            if actual[name]!=content:(TARGET/name).write_bytes(content)
else:
    for name,content in files.items():
        path=TARGET/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
print(json.dumps({'status':'PROPOSED','files':len(entries),'manifest_sha256':hashlib.sha256(files['manifest.json']).hexdigest(),
    'unchanged_schemas':sum(name.startswith('schemas/') for name in files),'unchanged_templates':sum(name.startswith('templates/') for name in files)},ensure_ascii=True))
