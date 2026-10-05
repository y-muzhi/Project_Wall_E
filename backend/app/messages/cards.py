"""SHR-CARDS semantics over frozen structures, without expiry clocks or writes."""
from backend.app.shared.validation import InvalidInput, strict_json_object, ordinary_text


class CardsInvalid(ValueError): pass


def validate_cards(value, protocol):
    cards = protocol.validate_cards(value)
    keys = [card['card_key'] for card in cards['cards']]
    if len(set(keys)) != len(keys): raise CardsInvalid('卡片键必须唯一')
    for card in cards['cards']:
        options = [option['option_key'] for option in card['options']]
        if len(set(options)) != len(options): raise CardsInvalid('选项键必须唯一')
        rule, custom = card['selection_rule'], card['custom_answer']
        if rule['min'] > rule['max'] or rule['max'] > len(options) + int(custom['enabled']): raise CardsInvalid('选择数量约束不合法')
        if custom['enabled'] and not 1 <= custom['max_length'] <= 2000 or not custom['enabled'] and custom['max_length'] != 0:
            raise CardsInvalid('自定义回答容量不合法')
        recommendation = card['recommendation']
        if recommendation is not None:
            proposed = recommendation['option_keys']
            if len(set(proposed)) != len(proposed) or not set(proposed) <= set(options): raise CardsInvalid('推荐只能引用现有选项')
    return cards


def validate_responses(value, cards, protocol):
    responses = protocol.validate_responses(value)
    keys = [item['card_key'] for item in responses['responses']]
    by_key = {item['card_key']: item for item in cards['cards']}
    if len(set(keys)) != len(keys) or set(keys) != set(by_key): raise CardsInvalid('回答必须准确覆盖整组卡片')
    for answer in responses['responses']:
        card = by_key[answer['card_key']]
        selected, custom = answer['selected_option_keys'], answer['custom_answer']
        if len(set(selected)) != len(selected) or not set(selected) <= {option['option_key'] for option in card['options']}:
            raise CardsInvalid('回答选项不属于原卡片或重复')
        if answer['skipped']:
            if card['required'] or selected or custom is not None: raise CardsInvalid('跳过只适用于完整空回答的非必答卡片')
            continue
        if custom is not None:
            if not card['custom_answer']['enabled']: raise CardsInvalid('卡片不允许自定义回答')
            try: normalized = ordinary_text(custom, 'custom_answer', 1, card['custom_answer']['max_length'])
            except InvalidInput: raise CardsInvalid('自定义回答不符合卡片限制') from None
            if normalized != custom: raise CardsInvalid('持久回答必须已完成普通文本规范化')
        count = len(selected) + int(custom is not None)
        if count == 0 or not card['selection_rule']['min'] <= count <= card['selection_rule']['max']:
            raise CardsInvalid('回答数量不符合卡片限制')
        if card['card_type'] in ('SINGLE_SELECT', 'CONFIRM') and count != 1: raise CardsInvalid('单选和确认只能给出一个回答')
    return responses


def decode_cards(raw, protocol):
    return validate_cards(strict_json_object(raw), protocol)


def decode_responses(raw, cards, protocol):
    return validate_responses(strict_json_object(raw), cards, protocol)
