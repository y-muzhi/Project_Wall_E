"""Versioned document structures for frontend and backend design."""

import hashlib
import json


DESIGN_PROFILES = {
    'FRONTEND_DESIGN': {
        'key': 'structure.frontend-design',
        'stored_kind': 'DESIGN',
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


def design_resource(kind, *, framework):
    profile = DESIGN_PROFILES[kind]
    content = json.dumps(
        {'headings': profile['headings'], 'rule': profile['rule']},
        ensure_ascii=False,
        separators=(',', ':'),
    )
    reference = {
        'key': profile['key'],
        'version': 'framework-v1' if framework else 'blank-v1',
        'digest': hashlib.sha256(content.encode('utf-8')).hexdigest(),
    }
    return reference, content


def design_resource_content(reference):
    kind = DESIGN_KEYS[reference['key']]
    expected, content = design_resource(kind, framework=reference['version'] == 'framework-v1')
    if reference != expected:
        raise ValueError('Design resource identity or digest does not match')
    return content


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
