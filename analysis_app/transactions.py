"""从事试制记录构造事务。

一个 lot 对应一次试制，因此是一个事务：同一 lot 的多条观测合并为一个事务，
items 内的重复组分归一为集合。良率按 size 加权汇总（size 只作为良率权重，
不参与支持度计数）；size 全为 0 时加权良率缺失。
"""
from collections import defaultdict


def parse_items(text):
    """分号分隔的组分文本归一化为去重、排序后的元组。"""
    return tuple(sorted({part.strip() for part in text.split(';') if part.strip()}))


def build_transactions(records):
    """按 lot 合并观测，返回按 lot 排序的事务列表。"""
    merged = {}
    order = []
    for row in records:
        lot = row['lot']
        if lot not in merged:
            merged[lot] = {
                'lot': lot,
                'plant': row['plant'],
                'month': row['month'],
                'items': set(),
                'weighted_sum': 0.0,
                'size_sum': 0,
                'observation_ids': [],
            }
            order.append(lot)
        transaction = merged[lot]
        if transaction['plant'] != row['plant'] or transaction['month'] != row['month']:
            raise ValueError(f'lot 跨工厂或月份登记不一致：{lot}')
        transaction['items'].update(parse_items(row['items']))
        size = row['size']
        if size > 0:
            transaction['weighted_sum'] += row['yield_rate'] * size
            transaction['size_sum'] += size
        transaction['observation_ids'].append(row['observation_id'])

    result = []
    for lot in order:
        transaction = merged[lot]
        total_size = transaction['size_sum']
        result.append({
            'lot': lot,
            'plant': transaction['plant'],
            'month': transaction['month'],
            'items': frozenset(transaction['items']),
            'weighted_yield': (transaction['weighted_sum'] / total_size
                               if total_size else None),
            'size': total_size,
            'source_rows': len(transaction['observation_ids']),
        })
    result.sort(key=lambda item: item['lot'])
    return result


def split_by_month(transactions, split_month):
    """发现集 month < split_month，验证集 month >= split_month。"""
    discovery = [t for t in transactions if t['month'] < split_month]
    validation = [t for t in transactions if t['month'] >= split_month]
    return discovery, validation


def item_vocabulary(transactions):
    counts = defaultdict(int)
    for transaction in transactions:
        for item in transaction['items']:
            counts[item] += 1
    return dict(sorted(counts.items()))
