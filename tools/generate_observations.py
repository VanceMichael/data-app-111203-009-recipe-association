"""生成本地合成试制记录 data/observations.csv。

仅使用标准库、固定随机种子，输出可复现。数据中的组分与工厂均为虚构，
各试验段（regime）的设计意图见 docs/data.md。

用法：
    python3 -I tools/generate_observations.py
"""
import csv
import random
from pathlib import Path

SEED = 20261113
PLANTS = ('P0', 'P1', 'P2')
MONTHS = range(12)
LOTS_PER_PLANT_MONTH = 8
SPLIT_MONTH = 8

BASELINE = {'P0': 0.84, 'P1': 0.75, 'P2': 0.66}
FILLER_RATE = {'P0': 0.75, 'P1': 0.35, 'P2': 0.10}
BC_EFFECT = 0.06
FILLER_EFFECT = -0.05
NOISE_SD = 0.03

LONG_ITEMS = tuple(f'L{i:02d}' for i in range(1, 17))


def main():
    rng = random.Random(SEED)
    rows = []
    seq = {plant: 0 for plant in PLANTS}

    def add_row(lot, plant, month, items, yield_rate, size, version):
        observation_id = f'obs-{plant}-{seq[plant]:02d}'
        seq[plant] += 1
        rows.append({
            'observation_id': observation_id,
            'lot': lot,
            'plant': plant,
            'month': month,
            'items': items,
            'yield_rate': f'{yield_rate:.12f}',
            'size': size,
            'recipe_version': version,
        })

    for plant in PLANTS:
        for month in MONTHS:
            version = 'V0' if month < 6 else 'V1'
            for index in range(LOTS_PER_PLANT_MONTH):
                lot = f'L-{plant}-{month:02d}-{index}'
                items = ['base']
                is_bc = rng.random() < 0.35
                binder = is_bc or rng.random() < 0.20
                coating = is_bc or rng.random() < 0.15
                if binder:
                    items.append('binder')
                if coating:
                    items.append('coating')

                # fiber：几乎只在 P0 试用；验证期 P0 全量使用，其它厂不再出现
                if plant == 'P0':
                    use_fiber = rng.random() < 0.5 if month < SPLIT_MONTH else True
                elif plant == 'P1' and month == 2 and index == 0:
                    use_fiber = True
                elif plant == 'P2' and month == 5 and index == 0:
                    use_fiber = True
                else:
                    use_fiber = False
                if use_fiber:
                    items.append('fiber')

                # filler：辛普森式分配，厂内效应为负，却集中在高基线工厂
                if rng.random() < FILLER_RATE[plant]:
                    items.append('filler')

                # pilot：仅发现期 P1 试用，验证期消失
                if plant == 'P1' and month < SPLIT_MONTH and rng.random() < 0.25:
                    items.append('pilot')

                # 验证期才出现的新组分
                if month >= SPLIT_MONTH and rng.random() < 0.30:
                    items.append('novel_a')
                if month >= SPLIT_MONTH and plant == 'P2' and rng.random() < 0.40:
                    items.append('novel_b')

                yield_rate = (BASELINE[plant]
                              + 0.002 * (month - 5.5)
                              + (BC_EFFECT if is_bc else 0.0)
                              + (FILLER_EFFECT if 'filler' in items else 0.0)
                              + rng.gauss(0.0, NOISE_SD))
                yield_rate = min(0.98, max(0.02, yield_rate))
                size = rng.randint(8, 40)

                # 少量行在 items 文本内重复组分，测试归一化
                if month in (1, 7) and index == 3:
                    items = [items[0], items[0]] + items[1:]
                add_row(lot, plant, month, ';'.join(items), yield_rate, size, version)

                # 同一 lot 的重复观测：合并为一个事务，组分取并集，良率按 size 加权
                if index == 1 and month in (3, 9):
                    extra_items = list(items)
                    if month == 3 and 'coating' not in extra_items:
                        extra_items.append('coating')
                    extra_yield = min(0.98, max(0.02, yield_rate + rng.gauss(0.0, 0.02)))
                    add_row(lot, plant, month, ';'.join(extra_items),
                            extra_yield, rng.randint(8, 40), version)

    # 超长配方：每厂一个 17 组分事务，默认参数下在一阶即因支持度不足被剪枝
    for plant in PLANTS:
        lot = f'L-{plant}-06-long'
        items = ['base', *LONG_ITEMS]
        yield_rate = min(0.98, max(0.02, BASELINE[plant] + rng.gauss(0.0, NOISE_SD)))
        add_row(lot, plant, 6, ';'.join(items), yield_rate, rng.randint(8, 40), 'V1')

    destination = Path('data/observations.csv')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            'observation_id', 'lot', 'plant', 'month', 'items',
            'yield_rate', 'size', 'recipe_version'])
        writer.writeheader()
        writer.writerows(rows)
    print(f'wrote {len(rows)} rows to {destination}')


if __name__ == '__main__':
    main()
