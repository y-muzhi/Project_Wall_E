"""Fixed EV-FORM-AI inputs and independent human criteria; no provider execution."""

from dataclasses import dataclass

FIXTURE_VERSION = 'formation-ev60-2'
FIXED_TIME = '2026-11-17T00:00:00.000Z'
BODIES = ('blank', 'fbase')
INPUTS = (
    '只解释推荐为何需要反馈，不改路线',
    '好友可帮忙推荐，先讨论是否纳入',
    '好友可帮忙推荐，先讨论是否纳入',
    '先给出可写入的推荐流程',
    '将s2拆成流程与异常两步，保留全部要求',
    '核对流程是否充分',
)
INITIAL_IDEA = (
    '形成个人电影推荐方案。明确候选、选择、推荐与反馈及异常边界；不接入外部片源。'
    '保留暂缓事项i2：首版是否纳入跨设备同步，归属s2，目前DEFERRED，本轮先聚焦推荐流程。'
)
BASE_BODY = '用户选择影片，系统给出推荐。\n\n用户可提交反馈。\n'
EDITED_FIRST = '系统列出候选影片，用户选择后获得三条推荐'
TASKS = (
    (
        'discuss',
        '普通说明及支线判断',
        '本轮只解释并判断是否需要独立跟踪，明确普通讨论、复用现有支线或新建跟踪的理由；'
        '不出写入卡或路线卡，不修改正文，不结束或重开步骤。',
    ),
    (
        'write',
        'STAGED_WRITE精确内容',
        '请给出一张STAGED_WRITE卡，形成s2.o1推荐流程的精确内容。空白正文使用FILL_EMPTY，DOCUMENT scope、完整markdown_content及空patches；'
        '有正文时只精确修订推荐流程块，原文必须命中，反馈块保持。'
        '说明与当前用户要求的关系，不把分析成果当正文，不直接写入。',
    ),
    (
        'path',
        'FORMATION_PATH_CHANGE完整路线',
        '请给出一张FORMATION_PATH_CHANGE卡，将s2拆成流程与异常两步，保留全部原要求。'
        '完整列出成果同kind承接、原问题和支线返回去向、依赖和顺序；不丢弃暂缓项。'
        '未携带完整实体的暂缓问题保留原归属与DEFERRED并说明，不擅自MOVE；'
        '使用合法临时引用，不直接保存路线，不修改正文，不自动结束或重开。',
    ),
    (
        'associate',
        'ASSOCIATE_CONTENT关联复核',
        '本轮明确复核人工修改后的当前正文与s2.o1的关联，原a1存在时给review_of；'
        '只使用实际可见的新版本与区块别名，不复活删除内容。'
        '若不足以证明关联，明确不确定及缺失材料；程序匹配不等于语义充分。'
        '不写入正文，不重开已结束节点，不出写入卡或路线卡。',
    ),
    (
        'assess',
        'ASSESS_STEP充分性及下一步',
        '请给出s2充分性评估及下一步建议，逐项说明s2.o1推荐流程和s2.o2范围判断的实际依据与缺口。'
        '材料不足必须GAPS_REMAIN或UNCERTAIN，不声称已经完成，不执行结束或重开，不出写入卡或路线卡。',
    ),
)


@dataclass(frozen=True)
class Sample:
    body: str
    input_no: int
    task: str

    @property
    def sample_id(self):
        return f'EV21-{self.body.upper()}-{self.input_no:02d}-{self.task.upper()}'

    @property
    def edited(self):
        return self.input_no == 6 or self.task == 'associate'

    @property
    def related_branch(self):
        return self.input_no == 3

    @property
    def closed(self):
        return (self.task == 'associate' and self.input_no % 2 == 1) or (
            self.task == 'assess' and self.input_no == 6
        )

    @property
    def instruction(self):
        directive = next(row[2] for row in TASKS if row[0] == self.task)
        return (
            '场景背景：' + INPUTS[self.input_no - 1] + '。\n\n'
            '本轮优先级：以上基元是场景背景；以下本样本任务明确本轮实际请求。'
            '若背景对是否出卡或拆步的描述与本样本任务不同，以本样本任务为准；'
            '系统授权、真实已确认范围及材料可见性仍必须遵守。\n\n本样本任务：' + directive
        )

    @property
    def criteria(self):
        common = (
            '仅按可见来源作答，不伪造已读、事实、采用或已保存；'
            '不得直接写正文、结束/重开或代用户处置；严格固定Output，无额外调用/修复。'
        )
        specific = {
            'discuss': (
                '输入3必须复用同问题OPEN b4，保持origin=s1/return=s2，不重复登记；'
                '无旧支线时按相关性及独立跟踪需要判断DISCUSS/NEW；新跟踪不等于批准纳入首版，单纯说明不强制新增支线。'
            ),
            'write': (
                '仅s2.o1 CONTENT；FILL_EMPTY只用于实际空正文；'
                '非空PATCH精确命中当前区块和版本，反馈块及范围外字节保持，不能凭空补来源。'
            ),
            'path': (
                's2.o1 CONTENT及s2.o2 ANALYSIS按kind完整承接，i1/i2及存在的b4去向完整；i2可保留原归属及DEFERRED，未带实体不得擅自MOVE，'
                '存在b4时origin仍s1；临时步/成果引用和完整顺序合法，无隐性丢项。'
            ),
            'associate': (
                '改稿后使用当前版本和实际区块别名；有a1时显式复核，'
                'CURRENT只表示程序可匹配；没有范围判断证据，不可据此声称全部充分。'
            ),
            'assess': (
                '已见流程只说明候选/选择/反馈，缺异常和独立范围判断依据；'
                '不得无依据SUFFICIENT，下一步为建议，不执行状态转换。'
            ),
        }
        return common + specific[self.task]


def samples():
    return tuple(
        Sample(body, number, task[0]) for body in BODIES for number in range(1, 7) for task in TASKS
    )
