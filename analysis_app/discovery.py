"""复验候选发现：发现期选规则、验证期固定规则集合做厂内条件关联。

流程边界（不可事后更改）：
1. 发现期（month < split_month）仅用于按批次支持度与最大阶数筛选规则；
2. 规则集合在进入验证期后冻结，验证期不再新增或替换规则；
3. 验证期（month >= split_month）只在同一工厂内比较规则命中/未命中批次的
   size 加权良率；跨厂只做覆盖汇总，不做跨厂合并检验；
4. BH 检验族 = 全部冻结规则在全部可检验工厂上的检验，一次性校正，
   不允许事后挑选最显著的分厂结果。

没有同厂可比样本（命中组或未命中组批次不足、或规则仅在一座工厂出现）的
规则只能作为共现发现，不输出良率关联结论。
"""
from .mining import mine_frequent_itemsets
from .statistics import benjamini_hochberg, compare_groups
from .transactions import build_transactions, item_vocabulary, split_by_month

DEFAULT_SPLIT_MONTH = 8
DEFAULT_MIN_SUPPORT = 5
DEFAULT_MAX_ORDER = 3
DEFAULT_MAX_CANDIDATE_SETS = 500
DEFAULT_MIN_LOTS_PER_GROUP = 5
DEFAULT_FDR = 0.05

INTERPRETATION = (
    '结果为相关性复验线索，不构成因果结论，不构成配方更换建议；'
    '规则在发现期按支持度筛选并冻结，验证期仅在同厂批次内比较加权良率。'
)


def discover(records, *, split_month=DEFAULT_SPLIT_MONTH,
             min_support=DEFAULT_MIN_SUPPORT, max_order=DEFAULT_MAX_ORDER,
             max_candidate_sets=DEFAULT_MAX_CANDIDATE_SETS,
             min_lots_per_group=DEFAULT_MIN_LOTS_PER_GROUP,
             fdr=DEFAULT_FDR):
    transactions = build_transactions(records)
    discovery_tx, validation_tx = split_by_month(transactions, split_month)
    plants = sorted({t['plant'] for t in transactions})

    frequent, mining_audit = mine_frequent_itemsets(
        discovery_tx, min_support, max_order, max_candidate_sets)

    discovery_vocab = item_vocabulary(discovery_tx)
    validation_vocab = item_vocabulary(validation_tx)
    novel_items = sorted(set(validation_vocab) - set(discovery_vocab))

    rules = [_build_rule(candidate, support, len(discovery_tx),
                         discovery_tx, validation_tx, plants,
                         min_lots_per_group)
             for candidate, support in frequent]

    test_entries = [((rule['rule_id'], plant), result['p_value'])
                    for rule in rules
                    for plant, result in rule['plant_results'].items()
                    if result['testable']]
    bh_family_size = len(test_entries)
    adjusted = benjamini_hochberg(test_entries)
    for rule in rules:
        for plant, result in rule['plant_results'].items():
            if result['testable']:
                result['bh_adj_p_value'] = adjusted[(rule['rule_id'], plant)]
                result['bh_significant'] = (
                    result['bh_adj_p_value'] <= fdr)
        _finalize_rule(rule, fdr, min_lots_per_group, plants)

    return {
        'product': 'recipe-association',
        'schema_version': 1,
        'analysis': 'discovery',
        'interpretation': INTERPRETATION,
        'parameters': {
            'split_month': split_month,
            'min_support_lots': min_support,
            'max_order': max_order,
            'max_candidate_sets': max_candidate_sets,
            'min_lots_per_group': min_lots_per_group,
            'fdr': fdr,
            'support_basis': '发现期去重后的 lot 事务计数；size 不参与支持度',
            'weight_basis': 'size 仅作为验证期良率均值的权重',
        },
        'periods': _period_summary(transactions, discovery_tx, validation_tx,
                                   split_month, plants),
        'mining': mining_audit,
        'novel_items_in_validation': [
            {'item': item, 'validation_support_lots': validation_vocab[item]}
            for item in novel_items
        ],
        'bh_test_family': {
            'boundary': ('全部冻结规则在全部可检验工厂上的厂内检验；'
                         '一次校正，不做事后分厂挑选'),
            'family_size': bh_family_size,
            'method': 'Benjamini-Hochberg',
            'fdr': fdr,
        },
        'rules': rules,
        'rule_verdict_counts': _verdict_counts(rules),
    }


def _period_summary(transactions, discovery_tx, validation_tx, split_month, plants):
    def block(part):
        per_plant = {}
        for plant in plants:
            members = [t for t in part if t['plant'] == plant]
            per_plant[plant] = {
                'transactions': len(members),
                'merged_from_rows': sum(t['source_rows'] for t in members),
            }
        return {
            'month_range': None,
            'transactions': len(part),
            'merged_from_rows': sum(t['source_rows'] for t in part),
            'distinct_items': len(item_vocabulary(part)),
            'per_plant': per_plant,
        }

    discovery = block(discovery_tx)
    validation = block(validation_tx)
    discovery['month_range'] = [
        min((t['month'] for t in discovery_tx), default=None),
        max((t['month'] for t in discovery_tx), default=None)]
    validation['month_range'] = [
        min((t['month'] for t in validation_tx), default=None),
        max((t['month'] for t in validation_tx), default=None)]
    return {
        'split_rule': f'发现期 month < {split_month}；验证期 month >= {split_month}',
        'all_transactions': len(transactions),
        'all_source_rows': sum(t['source_rows'] for t in transactions),
        'discovery': discovery,
        'validation': validation,
    }


def _build_rule(candidate, discovery_support, discovery_total,
                discovery_tx, validation_tx, plants, min_lots_per_group):
    members = tuple(sorted(candidate))
    rule_id = 'R' + '|'.join(members)
    rule = {
        'rule_id': rule_id,
        'itemset': members,
        'order': len(members),
        'discovery_support_lots': discovery_support,
        'discovery_support_rate': (discovery_support / discovery_total
                                   if discovery_total else None),
        'validation_support_lots': 0,
        'validation_support_rate': None,
        'validation_presence_plants': [],
        'plant_results': {},
        'verdict': None,
        'verdict_reasons': [],
        'simpson_conflict': False,
    }

    validation_present = [t for t in validation_tx if candidate <= t['items']]
    rule['validation_support_lots'] = len(validation_present)
    if validation_tx:
        rule['validation_support_rate'] = len(validation_present) / len(validation_tx)
    presence_plants = sorted({t['plant'] for t in validation_present})
    rule['validation_presence_plants'] = presence_plants

    pooled_present = [t for t in validation_present
                      if t['weighted_yield'] is not None]
    pooled_absent = [t for t in validation_tx
                     if not candidate <= t['items']
                     and t['weighted_yield'] is not None]
    pooled = compare_groups(pooled_present, pooled_absent, min_lots_per_group)
    # 总体效应仅作描述与辛普森冲突判断，不进入 BH 检验族（检验只在厂内进行）
    rule['pooled_validation'] = {
        'present_lots': pooled['present_lots'],
        'absent_lots': pooled['absent_lots'],
        'present_weighted_yield': pooled['present_weighted_yield'],
        'absent_weighted_yield': pooled['absent_weighted_yield'],
        'effect': pooled['effect'],
        'note': '跨厂合并口径，可能受工厂构成混杂；显著性以厂内检验为准',
    }

    for plant in plants:
        members_tx = [t for t in validation_tx if t['plant'] == plant]
        present = [t for t in members_tx if candidate <= t['items']
                   and t['weighted_yield'] is not None]
        absent = [t for t in members_tx if not candidate <= t['items']
                  and t['weighted_yield'] is not None]
        result = compare_groups(present, absent, min_lots_per_group)
        result['validation_lots_in_plant'] = len(members_tx)
        rule['plant_results'][plant] = result

    if pooled['testable']:
        within_effects = [result['effect'] for result in rule['plant_results'].values()
                          if result['testable']]
        rule['simpson_conflict'] = bool(
            within_effects
            and pooled['effect'] > 0
            and all(effect < 0 for effect in within_effects))
    return rule


def _finalize_rule(rule, fdr, min_lots_per_group, plants):
    reasons = []
    if rule['validation_support_lots'] == 0:
        rule['verdict'] = 'eliminated_validation_empty'
        reasons.append('验证期无命中批次，规则无法复验')
        rule['verdict_reasons'] = reasons
        rule['stability'] = _stability(rule)
        return

    testable_plants = [plant for plant, result in rule['plant_results'].items()
                       if result['testable']]
    if not testable_plants:
        rule['verdict'] = 'cooccurrence_only'
        if len(rule['validation_presence_plants']) <= 1:
            reasons.append('规则在验证期仅出现于一座工厂，无同厂可比样本')
        else:
            reasons.append(f'命中组或未命中组批次少于 {min_lots_per_group}，'
                           '厂内条件关联不可检验')
        rule['verdict_reasons'] = reasons
        rule['stability'] = _stability(rule)
        return

    significant_plants = [plant for plant in testable_plants
                          if rule['plant_results'][plant]['bh_significant']]
    if not significant_plants:
        rule['verdict'] = 'not_validated'
        reasons.append(f'BH 校正后无工厂在 FDR={fdr} 水平显著')
    elif len(testable_plants) < 2:
        rule['verdict'] = 'cooccurrence_only'
        reasons.append('仅一座工厂具备同厂可比样本，跨厂覆盖不足，'
                       '不能把工厂优势表述为组分协同')
    else:
        effects = [rule['plant_results'][plant]['effect']
                   for plant in significant_plants]
        if all(effect > 0 for effect in effects):
            rule['verdict'] = 'validated_association'
            reasons.append('多厂同方向且 BH 校正后显著，可作为复验候选线索')
        elif all(effect < 0 for effect in effects):
            rule['verdict'] = 'validated_association'
            reasons.append('多厂同方向负关联且 BH 校正后显著，可作为复验候选线索')
        else:
            rule['verdict'] = 'not_validated'
            reasons.append('显著工厂的效应方向不一致，稳定性不足')

    missing_plants = sorted(set(plants) - set(testable_plants))
    if missing_plants:
        reasons.append('无同厂可比样本的工厂：' + ','.join(missing_plants))
    if rule['simpson_conflict']:
        reasons.append('总体正相关而各厂负相关（辛普森式冲突），'
                       '以厂内结果为准')
    rule['verdict_reasons'] = reasons
    rule['stability'] = _stability(rule)


def _stability(rule):
    """跨厂覆盖与方向稳定性汇总，供业务侧快速判断证据强度。"""
    testable = [plant for plant, result in rule['plant_results'].items()
                if result['testable']]
    significant = [plant for plant in testable
                   if rule['plant_results'][plant]['bh_significant']]
    effects = [rule['plant_results'][plant]['effect'] for plant in testable]
    positive = sum(1 for effect in effects if effect > 0)
    negative = sum(1 for effect in effects if effect < 0)
    return {
        'testable_plants': testable,
        'significant_plants': significant,
        'presence_plants': rule['validation_presence_plants'],
        'positive_effect_plants': positive,
        'negative_effect_plants': negative,
        'direction_consistent': (
            bool(effects) and (positive == len(effects) or negative == len(effects))),
    }


def _verdict_counts(rules):
    counts = {}
    for rule in rules:
        counts[rule['verdict']] = counts.get(rule['verdict'], 0) + 1
    return dict(sorted(counts.items()))
