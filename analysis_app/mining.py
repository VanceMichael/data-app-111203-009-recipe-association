"""有界频繁项集挖掘。

采用逐层（类 Apriori）枚举：只有当上一阶全部子集都频繁时才生成候选，
并同时受 max_order 与 max_candidate_sets 两个硬上限约束，不枚举无界幂集。
支持度按事务（lot）计数，与 size 无关。每个被淘汰的候选都记录原因，
便于业务侧核对规则是如何被筛掉的。
"""
from itertools import combinations


def mine_frequent_itemsets(transactions, min_support, max_order, max_candidate_sets):
    """返回 (频繁项集列表, 审计信息)。

    频繁项集元素为 (frozenset, 支持批次数)，按阶数、组分名排序。
    候选预算耗尽时停止向更高阶扩展，并在审计信息中标记 truncated。
    审计信息中的 eliminations 记录每个候选的淘汰原因：
      below_min_support：支持批次不足；
      order_cap：达到最大组合阶数，不再向更高阶扩展；
      budget_truncated：候选集合预算耗尽，未评估的高阶候选。
    """
    if min_support < 1:
        raise ValueError('最小支持度按批次计，必须为不小于 1 的整数')
    if max_order < 1:
        raise ValueError('最大组合阶数必须不小于 1')
    if max_candidate_sets < 1:
        raise ValueError('候选集合预算必须不小于 1')

    n_transactions = len(transactions)
    item_counts = {}
    for transaction in transactions:
        for item in transaction['items']:
            item_counts[item] = item_counts.get(item, 0) + 1

    eliminations = []
    first_level = []
    for item in sorted(item_counts):
        candidate = frozenset((item,))
        if item_counts[item] >= min_support:
            first_level.append(candidate)
        else:
            eliminations.append({
                'itemset': tuple(sorted(candidate)),
                'order': 1,
                'support_lots': item_counts[item],
                'reason': 'below_min_support',
            })

    frequent = []
    candidates_evaluated = 0
    truncated = False
    current = first_level
    order = 1
    while current and order <= max_order:
        if candidates_evaluated + len(current) > max_candidate_sets:
            for candidate in current:
                eliminations.append({
                    'itemset': tuple(sorted(candidate)),
                    'order': len(candidate),
                    'support_lots': None,
                    'reason': 'budget_truncated',
                })
            truncated = True
            break
        candidates_evaluated += len(current)
        counts = _support_counts(current, transactions)
        kept = []
        for candidate in current:
            if counts[candidate] >= min_support:
                kept.append(candidate)
                frequent.append((candidate, counts[candidate]))
            else:
                eliminations.append({
                    'itemset': tuple(sorted(candidate)),
                    'order': len(candidate),
                    'support_lots': counts[candidate],
                    'reason': 'below_min_support',
                })
        if order == max_order:
            if kept:
                eliminations.append({
                    'itemset': None,
                    'order': order,
                    'support_lots': None,
                    'reason': 'order_cap',
                })
            break
        next_level = _next_candidates(kept, order + 1)
        current = next_level
        order += 1

    frequent.sort(key=lambda entry: (len(entry[0]), sorted(entry[0])))
    eliminations.sort(key=lambda entry: (entry['order'],
                                         entry['itemset'] or ()))
    audit = {
        'transactions_scanned': n_transactions,
        'candidate_sets_evaluated': candidates_evaluated,
        'candidate_budget': max_candidate_sets,
        'truncated_by_budget': truncated,
        'max_order_reached': min(order, max_order),
        'eliminations': eliminations,
        'elimination_reason_counts': _count_reasons(eliminations, truncated),
    }
    return frequent, audit


def _count_reasons(eliminations, truncated):
    counts = {}
    for entry in eliminations:
        counts[entry['reason']] = counts.get(entry['reason'], 0) + 1
    return dict(sorted(counts.items()))


def _support_counts(candidates, transactions):
    counts = {candidate: 0 for candidate in candidates}
    for transaction in transactions:
        items = transaction['items']
        for candidate in candidates:
            if candidate <= items:
                counts[candidate] += 1
    return counts


def _next_candidates(frequent_sets, next_order):
    """自连接生成下一阶候选，并要求其所有直接子集均频繁（先验剪枝）。"""
    frequent_set = set(frequent_sets)
    candidates = set()
    for left, right in combinations(frequent_sets, 2):
        union = left | right
        if len(union) != next_order:
            continue
        if all(frozenset(sub) in frequent_set
               for sub in combinations(sorted(union), next_order - 1)):
            candidates.add(union)
    return sorted(candidates, key=lambda candidate: sorted(candidate))
