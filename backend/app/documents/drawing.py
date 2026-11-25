"""The Excalidraw representation carried by existing document snapshots."""

import base64
import binascii
import json
import re

from backend.app.shared.validation import InvalidInput, strict_json_object

from .design_profiles import DRAWING_KIND, design_document_kind
from .markdown import DocumentInvalid

FENCE = '```excalidraw\n'
END_FENCE = '\n```\n'
EMPTY_SCENE = {
    'type': 'excalidraw',
    'version': 2,
    'source': 'WALL-E',
    'elements': [],
    'appState': {'viewBackgroundColor': '#ffffff'},
    'files': {},
}
ELEMENT_TYPES = frozenset(
    {'rectangle', 'diamond', 'ellipse', 'arrow', 'line', 'freedraw', 'text', 'image', 'frame'}
)


def empty_drawing() -> str:
    return FENCE + json.dumps(EMPTY_SCENE, separators=(',', ':')) + END_FENCE


def is_drawing(row) -> bool:
    return design_document_kind(row['document_kind'], row['template_ref']) == DRAWING_KIND


def validate_drawing(markdown: str) -> None:
    match = re.fullmatch(r'(`{3,})excalidraw\n([^\r\n]+)\n\1\n', markdown)
    if match is None:
        raise DocumentInvalid('画板必须包含一个完整场景')
    try:
        scene = strict_json_object(match[2], field='drawing')
    except InvalidInput as error:
        raise DocumentInvalid('画板场景不是有效 JSON') from error
    if (
        set(scene) != set(EMPTY_SCENE)
        or scene['type'] != 'excalidraw'
        or type(scene['version']) is not int
        or scene['version'] != 2
        or scene['source'] != 'WALL-E'
        or type(scene['elements']) is not list
        or type(scene['appState']) is not dict
        or type(scene['files']) is not dict
    ):
        raise DocumentInvalid('画板场景格式不受支持')
    state = scene['appState']
    if (
        set(state) != {'viewBackgroundColor'}
        or type(state['viewBackgroundColor']) is not str
        or not 1 <= len(state['viewBackgroundColor']) <= 64
    ):
        raise DocumentInvalid('画板背景属性无效')
    identities = set()
    used_files = set()
    for element in scene['elements']:
        if (
            type(element) is not dict
            or type(element.get('id')) is not str
            or not element['id']
            or element['id'] in identities
            or type(element.get('type')) is not str
            or element['type'] not in ELEMENT_TYPES
            or element.get('isDeleted') is not False
            or any(
                type(element.get(key)) not in (int, float) for key in ('x', 'y', 'width', 'height')
            )
        ):
            raise DocumentInvalid('画板图形无效')
        identities.add(element['id'])
        if element['type'] == 'image':
            identity = element.get('fileId')
            if type(identity) is not str or not identity or element.get('status') != 'saved':
                raise DocumentInvalid('画板图片尚不可用')
            used_files.add(identity)
    if used_files != set(scene['files']):
        raise DocumentInvalid('画板图片引用不完整')
    for identity, file in scene['files'].items():
        if type(file) is not dict or file.get('id') != identity:
            raise DocumentInvalid('画板图片身份无效')
        mime_type, data_url = file.get('mimeType'), file.get('dataURL')
        if (
            type(mime_type) is not str
            or not mime_type.startswith('image/')
            or type(data_url) is not str
            or not data_url.startswith(f'data:{mime_type};base64,')
        ):
            raise DocumentInvalid('画板图片必须保存完整数据')
        try:
            data = base64.b64decode(data_url.split(',', 1)[1], validate=True)
        except (binascii.Error, ValueError) as error:
            raise DocumentInvalid('画板图片数据无效') from error
        if not data:
            raise DocumentInvalid('画板图片数据为空')
