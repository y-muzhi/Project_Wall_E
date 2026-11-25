"""Versioned document structures for frontend and backend design."""

import hashlib
import json
from functools import cache
from pathlib import Path


DRAWING_KIND = 'DRAWING'

DESIGN_PROFILES = {
    DRAWING_KIND: {
        'key': 'structure.excalidraw',
        'stored_kind': 'DESIGN',
        'headings': (),
        'rule': '独立画板使用 Excalidraw 场景，只允许人工编辑。',
    },
    'FRONTEND_DESIGN': {
        'key': 'structure.frontend-design',
        'stored_kind': 'DESIGN',
        'framework_file': 'frontend.md',
        'framework_sha256': '029b2fee9728a4a1554d5e7d3650ccee4c1a9e0c8da93ca2cbed6aa275e9f787',
        'headings': (
            '设计目标与范围',
            '页面与导航',
            '组件与交互',
            '数据展示与接口依赖',
            '状态、异常与恢复',
            '前端验收',
        ),
        'rule': '按前端设计的职责描述页面、导航、组件和交互，明确加载、空态、错误及恢复；'
        '引用后端接口契约，避免重复定义存储和服务端规则。',
    },
    'BACKEND_DESIGN': {
        'key': 'structure.backend-design',
        'stored_kind': 'SPECIFICATION',
        'framework_file': 'backend.md',
        'framework_sha256': 'a046ca30e9ded4101d1658c61f9aef94de15510bd068a8ac1542e66011e4ae40',
        'headings': (
            '设计目标与范围',
            '业务对象与状态',
            '业务规则与流程',
            '接口与外部依赖',
            '存储、权限与异常处理',
            '后端验收',
        ),
        'rule': '按后端设计的职责描述业务对象、状态、流程、接口和存储，明确权限、异常和恢复；'
        '保留前端依赖的契约，避免重复描述页面布局和组件交互。',
    },
}
DESIGN_KINDS = tuple(DESIGN_PROFILES)
DESIGN_KEYS = {profile['key']: kind for kind, profile in DESIGN_PROFILES.items()}
FRAMEWORK_VERSION = 'framework-v2'
_FRAMEWORK_V2_DIRECTORY = Path(__file__).resolve().parents[2] / 'resources/design-frameworks/v2'


@cache
def _framework_v2(kind):
    from backend.app.infrastructure.resources import ConfigInvalid

    profile = DESIGN_PROFILES[kind]
    try:
        raw = (_FRAMEWORK_V2_DIRECTORY / profile['framework_file']).read_bytes()
        markdown = raw.decode('utf-8')
    except (OSError, UnicodeError) as error:
        raise ConfigInvalid('Built-in design framework unavailable') from error
    if hashlib.sha256(raw).hexdigest() != profile['framework_sha256']:
        raise ConfigInvalid('Built-in design framework digest differs')
    headings = tuple(line[2:] for line in markdown.splitlines() if line.startswith('# '))
    return markdown, headings


def _versioned_design_resource(kind, version):
    profile = DESIGN_PROFILES[kind]
    if version in ('blank-v1', 'framework-v1'):
        description = {'headings': profile['headings'], 'rule': profile['rule']}
    elif version == 'framework-v2':
        _, headings = _framework_v2(kind)
        description = {
            'headings': headings,
            'rule': profile['rule'] + '遵循正文的完整规格填写说明及字段表，只填写本次授权范围。',
            'markdown_sha256': profile['framework_sha256'],
        }
    else:
        raise ValueError('Unknown design resource version')
    content = json.dumps(
        description,
        ensure_ascii=False,
        separators=(',', ':'),
    )
    reference = {
        'key': profile['key'],
        'version': version,
        'digest': hashlib.sha256(content.encode('utf-8')).hexdigest(),
    }
    return reference, content


def design_resource(kind, *, framework):
    return _versioned_design_resource(kind, FRAMEWORK_VERSION if framework else 'blank-v1')


def design_resource_content(reference):
    kind = DESIGN_KEYS[reference['key']]
    expected, content = _versioned_design_resource(kind, reference['version'])
    if reference != expected:
        raise ValueError('Design resource identity or digest does not match')
    return content


def matches_design_framework(kind, reference):
    if reference is None or reference['version'] not in ('framework-v1', 'framework-v2'):
        return False
    expected, _ = _versioned_design_resource(kind, reference['version'])
    return reference == expected


def design_framework_markdown(reference):
    design_resource_content(reference)
    kind = DESIGN_KEYS[reference['key']]
    if reference['version'] == 'framework-v1':
        return '\n\n'.join('# ' + heading for heading in DESIGN_PROFILES[kind]['headings']) + '\n'
    if reference['version'] == 'framework-v2':
        return _framework_v2(kind)[0]
    raise ValueError('Design resource has no initial Markdown')


def design_document_kind(stored_kind, template_ref):
    if template_ref is None:
        return stored_kind
    reference = json.loads(template_ref) if isinstance(template_ref, str) else template_ref
    kind = DESIGN_KEYS.get(reference['key'])
    if kind is None:
        return stored_kind
    design_resource_content(reference)
    if DESIGN_PROFILES[kind]['stored_kind'] != stored_kind:
        raise ValueError('Design resource does not belong to this document')
    return kind
