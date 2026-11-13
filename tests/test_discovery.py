import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from itertools import combinations
from pathlib import Path

from analysis_app.discovery import discover
from analysis_app.mining import mine_frequent_itemsets
from analysis_app.schema import FIELDS
from analysis_app.statistics import benjamini_hochberg, compare_groups
from analysis_app.transactions import build_transactions, parse_items, split_by_month


def make_row(observation_id, lot, plant, month, items,
             yield_rate=0.7, size=10, version='V0'):
    return {
        'observation_id': observation_id,
        'lot': lot,
        'plant': plant,
        'month': month,
        'items': ';'.join(items),
        'yield_rate': yield_rate,
        'size': size,
        'recipe_version': version,
    }


def write_csv(directory, rows):
    path = Path(directory) / 'input.csv'
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def records_from_spec(spec):
    """spec: 列表，每项 (lot, plant, month, items, yield_rate[, size])。"""
    rows = []
    for index, item in enumerate(spec):
        lot, plant, month, items, yield_rate = item[:5]
        size = item[5] if len(item) > 5 else 10
        rows.append(make_row(f'obs-{index:03d}', lot, plant, month,
                             items, yield_rate, size))
    return rows


def rule_by_itemset(result, itemset):
    target = tuple(sorted(itemset))
    for rule in result['rules']:
        if tuple(rule['itemset']) == target:
            return rule
    raise KeyError(target)


class TransactionTest(unittest.TestCase):
    def test_duplicate_items_are_normalized(self):
        self.assertEqual(parse_items('a;b;a; ;b'), ('a', 'b'))

    def test_same_lot_is_one_transaction_with_union_and_weighted_yield(self):
        rows = [
            make_row('o1', 'L1', 'P0', 1, ['a', 'b'], 0.5, size=2),
            make_row('o2', 'L1', 'P0', 1, ['b', 'c'], 0.9, size=6),
        ]
        tx = build_transactions(rows)
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx[0]['items'], frozenset({'a', 'b', 'c'}))
        self.assertEqual(tx[0]['size'], 8)
        self.assertAlmostEqual(tx[0]['weighted_yield'], 0.8)
        self.assertEqual(tx[0]['source_rows'], 2)

    def test_zero_size_lot_has_missing_weighted_yield_but_counts_as_transaction(self):
        rows = [make_row('o1', 'L1', 'P0', 1, ['a'], 0.7, size=0)]
        tx = build_transactions(rows)
        self.assertEqual(len(tx), 1)
        self.assertIsNone(tx[0]['weighted_yield'])

    def test_lot_cannot_span_plant_or_month(self):
        rows = [
            make_row('o1', 'L1', 'P0', 1, ['a']),
            make_row('o2', 'L1', 'P1', 1, ['a']),
        ]
        with self.assertRaisesRegex(ValueError, 'lot 跨工厂或月份'):
            build_transactions(rows)

    def test_split_uses_month_boundary(self):
        tx = build_transactions(records_from_spec([
            ('L1', 'P0', 7, ['a'], 0.7),
            ('L2', 'P0', 8, ['a'], 0.7),
            ('L3', 'P0', 9, ['a'], 0.7),
        ]))
        discovery, validation = split_by_month(tx, 8)
        self.assertEqual({t['lot'] for t in discovery}, {'L1'})
        self.assertEqual({t['lot'] for t in validation}, {'L2', 'L3'})


class MiningTest(unittest.TestCase):
    def setUp(self):
        self.records = records_from_spec([
            ('L1', 'P0', 0, ['a', 'b'], 0.7),
            ('L2', 'P0', 0, ['a', 'b'], 0.7),
            ('L3', 'P0', 0, ['a', 'c'], 0.7),
            ('L4', 'P0', 0, ['b', 'c'], 0.7),
        ])
        self.tx = build_transactions(self.records)

    def test_support_counts_lots_not_sizes(self):
        rows = records_from_spec([
            ('L1', 'P0', 0, ['a'], 0.7, 100),
            ('L2', 'P0', 0, ['a'], 0.7, 1),
            ('L3', 'P0', 0, ['b'], 0.7, 50),
        ])
        frequent, audit = mine_frequent_itemsets(build_transactions(rows), 2, 2, 100)
        supports = {tuple(sorted(itemset)): support for itemset, support in frequent}
        self.assertEqual(supports[('a',)], 2)
        self.assertNotIn(('b',), supports)

    def test_apriori_pruning_and_elimination_ledger(self):
        records = records_from_spec([
            ('L1', 'P0', 0, ['a', 'b', 'c'], 0.7),
            ('L2', 'P0', 0, ['a', 'b', 'c'], 0.7),
            ('L3', 'P0', 0, ['a', 'b', 'd'], 0.7),
            ('L4', 'P0', 0, ['a', 'c', 'd'], 0.7),
        ])
        frequent, audit = mine_frequent_itemsets(
            build_transactions(records), 2, 2, 100)
        found = {tuple(sorted(itemset)) for itemset, _ in frequent}
        self.assertIn(('a', 'b'), found)
        # 没有任何 3 阶频繁集输出；阶数上限与支持度淘汰均应留痕
        self.assertTrue(all(len(itemset) <= 2 for itemset, _ in frequent))
        reasons = {entry['reason'] for entry in audit['eliminations']}
        self.assertIn('below_min_support', reasons)
        self.assertIn('order_cap', reasons)

    def test_candidate_budget_is_hard_cap(self):
        frequent, audit = mine_frequent_itemsets(self.tx, 1, 3, 2)
        self.assertTrue(audit['truncated_by_budget'])
        self.assertLessEqual(audit['candidate_sets_evaluated'], 2)
        self.assertTrue(any(entry['reason'] == 'budget_truncated'
                            for entry in audit['eliminations']))

    def test_max_order_caps_enumeration(self):
        long_records = records_from_spec([
            (f'L{i}', 'P0', 0, [f'x{j}' for j in range(8)], 0.7)
            for i in range(6)])
        frequent, audit = mine_frequent_itemsets(
            build_transactions(long_records), 2, 2, 10_000)
        self.assertTrue(all(len(itemset) <= 2 for itemset, _ in frequent))
        # 证明幂集未被枚举：8 个组分的 3+ 阶子集共 219 个，评估数远小于此
        self.assertLess(audit['candidate_sets_evaluated'],
                        sum(1 for r in range(1, 9) for _ in combinations(range(8), r)))

    def test_invalid_arguments_rejected(self):
        with self.assertRaisesRegex(ValueError, '最小支持度'):
            mine_frequent_itemsets(self.tx, 0, 2, 100)
        with self.assertRaisesRegex(ValueError, '最大组合阶数'):
            mine_frequent_itemsets(self.tx, 1, 0, 100)


class StatisticsTest(unittest.TestCase):
    def _groups(self, present, absent):
        def build(values):
            return [{'size': size, 'weighted_yield': rate} for rate, size in values]
        return build(present), build(absent)

    def test_untestable_when_group_below_min_lots(self):
        present, absent = self._groups([(0.9, 10)], [(0.5, 10)] * 5)
        result = compare_groups(present, absent, min_lots=5)
        self.assertFalse(result['testable'])
        self.assertIsNone(result['p_value'])

    def test_effect_direction_and_two_sided_p(self):
        present, absent = self._groups(
            [(0.72 + 0.01 * i, 10) for i in range(8)],
            [(0.69 + 0.01 * i, 10) for i in range(8)])
        result = compare_groups(present, absent, min_lots=5)
        self.assertTrue(result['testable'])
        self.assertAlmostEqual(result['effect'], 0.03)
        self.assertGreater(result['z_score'], 0)
        self.assertGreater(result['p_value'], 0.0)
        self.assertLess(result['p_value'], 0.05)

    def test_zero_variance_is_serializable(self):
        present, absent = self._groups(
            [(0.9, 10)] * 6, [(0.5, 10)] * 6)
        result = compare_groups(present, absent, min_lots=5)
        self.assertTrue(result['zero_variance'])
        self.assertEqual(result['p_value'], 0.0)
        self.assertIsNone(result['z_score'])
        json.dumps(result, allow_nan=False)

    def test_benjamini_hochberg_known_values(self):
        # 手算：p=[0.01,0.02,0.4]，m=3
        # 调整值 = min(1, m/rank*p) 并从大秩向小秩取累积最小
        adjusted = benjamini_hochberg([('a', 0.01), ('b', 0.02), ('c', 0.4)])
        self.assertAlmostEqual(adjusted['a'], 0.03)
        self.assertAlmostEqual(adjusted['b'], 0.03)
        self.assertAlmostEqual(adjusted['c'], 0.4)

    def test_bh_family_size_changes_adjustment(self):
        small = benjamini_hochberg([('a', 0.01), ('b', 0.02)])
        larger = benjamini_hochberg(
            [('a', 0.01), ('b', 0.02), ('c', 0.4), ('d', 0.5)])
        self.assertNotEqual(small['a'], larger['a'])


class DiscoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from analysis_app.io import load_records
        cls.records = load_records('data/observations.csv')
        cls.result = discover(cls.records)

    def test_transaction_scale_after_dedup(self):
        periods = self.result['periods']
        self.assertEqual(periods['all_source_rows'], 297)
        self.assertLess(periods['all_transactions'], periods['all_source_rows'])
        self.assertEqual(periods['all_transactions'],
                         periods['discovery']['transactions']
                         + periods['validation']['transactions'])

    def test_discovery_is_deterministic_and_input_order_independent(self):
        shuffled = copy.deepcopy(self.records)
        import random
        random.Random(7).shuffle(shuffled)
        self.assertEqual(discover(shuffled), self.result)

    def test_novel_items_only_appear_in_validation(self):
        names = {entry['item'] for entry in
                 self.result['novel_items_in_validation']}
        self.assertEqual(names, {'novel_a', 'novel_b'})
        rule_items = {tuple(rule['itemset']) for rule in self.result['rules']}
        self.assertNotIn(('novel_a',), rule_items)
        self.assertNotIn(('novel_b',), rule_items)

    def test_long_recipe_items_pruned_with_ledger_and_no_powerset(self):
        audit = self.result['mining']
        self.assertFalse(audit['truncated_by_budget'])
        long_entries = [entry for entry in audit['eliminations']
                        if entry['itemset'] and entry['itemset'][0].startswith('L')]
        self.assertEqual(len(long_entries), 16)
        self.assertTrue(all(entry['reason'] == 'below_min_support'
                            for entry in long_entries))
        for rule in self.result['rules']:
            self.assertLessEqual(rule['order'], 3)

    def test_fiber_is_cooccurrence_only_single_plant(self):
        rule = rule_by_itemset(self.result, ('fiber',))
        self.assertEqual(rule['verdict'], 'cooccurrence_only')
        self.assertEqual(rule['validation_presence_plants'], ['P0'])
        for plant, plant_result in rule['plant_results'].items():
            self.assertFalse(plant_result['testable'])
        self.assertTrue(any('一座工厂' in reason for reason in rule['verdict_reasons']))

    def test_pilot_rule_set_eliminated_in_validation(self):
        rule = rule_by_itemset(self.result, ('pilot',))
        self.assertEqual(rule['verdict'], 'eliminated_validation_empty')
        self.assertEqual(rule['validation_support_lots'], 0)

    def test_simpson_regime_pooled_positive_within_plant_negative(self):
        rule = rule_by_itemset(self.result, ('filler',))
        self.assertTrue(rule['simpson_conflict'])
        self.assertGreater(rule['pooled_validation']['effect'], 0)
        for plant, plant_result in rule['plant_results'].items():
            self.assertTrue(plant_result['testable'])
            self.assertLess(plant_result['effect'], 0)
        self.assertTrue(any('辛普森' in reason for reason in rule['verdict_reasons']))

    def test_stable_binder_coating_combo_validated_across_plants(self):
        rule = rule_by_itemset(self.result, ('binder', 'coating'))
        self.assertEqual(rule['verdict'], 'validated_association')
        testable = [plant for plant, result in rule['plant_results'].items()
                    if result['testable']]
        self.assertEqual(sorted(testable), ['P0', 'P1', 'P2'])
        effects = [rule['plant_results'][plant]['effect'] for plant in testable]
        self.assertTrue(all(effect > 0 for effect in effects))
        self.assertTrue(all(rule['plant_results'][plant]['bh_significant']
                            for plant in testable))

    def test_bh_family_boundary_includes_all_testable_plant_tests_once(self):
        family = self.result['bh_test_family']
        expected = sum(1 for rule in self.result['rules']
                       for plant_result in rule['plant_results'].values()
                       if plant_result['testable'])
        self.assertEqual(family['family_size'], expected)
        seen = set()
        for rule in self.result['rules']:
            for plant, plant_result in rule['plant_results'].items():
                if plant_result['testable']:
                    seen.add((rule['rule_id'], plant))
                    self.assertIn('bh_adj_p_value', plant_result)
                    self.assertGreaterEqual(plant_result['bh_adj_p_value'],
                                            plant_result['p_value'] - 1e-12)
        self.assertEqual(len(seen), expected)

    def test_output_carries_correlation_not_causation_notice(self):
        self.assertIn('不构成因果结论', self.result['interpretation'])
        for rule in self.result['rules']:
            self.assertTrue(rule['verdict_reasons'])

    def test_empty_validation_rule_set(self):
        # 全部事务都落在发现期：规则集合冻结后验证集为空
        rows = records_from_spec([
            (f'L{i}', 'P0', 0, ['a', 'b'], 0.7 + 0.01 * i)
            for i in range(10)])
        result = discover(rows, split_month=12, min_support=3)
        self.assertEqual(result['periods']['validation']['transactions'], 0)
        self.assertTrue(result['rules'])
        for rule in result['rules']:
            self.assertEqual(rule['verdict'], 'eliminated_validation_empty')
        self.assertEqual(result['bh_test_family']['family_size'], 0)

    def test_validation_disappearance_freezes_rules_then_eliminates_them(self):
        # 发现期组分在验证期全部消失：规则集合在发现期冻结，验证期逐一淘汰，
        # 而验证期新组分只登记为 novel，不允许事后加入规则集合
        rows = records_from_spec(
            [(f'D{i}', 'P0', 0, ['a', 'b'], 0.7) for i in range(6)]
            + [(f'V{i}', 'P0', 8, ['c', 'd'], 0.7) for i in range(6)])
        result = discover(rows, split_month=8, min_support=3)
        self.assertTrue(result['rules'])
        self.assertTrue(all(rule['verdict'] == 'eliminated_validation_empty'
                            for rule in result['rules']))
        self.assertEqual(
            {entry['item'] for entry in result['novel_items_in_validation']},
            {'c', 'd'})
        rule_items = {tuple(rule['itemset']) for rule in result['rules']}
        self.assertNotIn(('c',), rule_items)
        self.assertNotIn(('d',), rule_items)

    def test_synthetic_simpson_fixture_flags_conflict(self):
        rows = []
        seq = 0
        # 高基线工厂 P0 大量使用 x；低基线工厂 P1 很少使用 x；厂内 x 效应为负
        for _ in range(30):
            rows.append(make_row(f'o{seq}', f'L{seq}', 'P0', 8,
                                 ['x'] if seq % 2 == 0 else ['base'],
                                 0.84 - (0.05 if seq % 2 == 0 else 0.0),
                                 10)); seq += 1
        for _ in range(30):
            use_x = seq % 5 == 0
            rows.append(make_row(f'o{seq}', f'L{seq}', 'P1', 8,
                                 ['x'] if use_x else ['base'],
                                 0.60 - (0.05 if use_x else 0.0), 10)); seq += 1
        discovery_rows = [make_row(f'd{i}', f'D{i}', 'P0', 0,
                                   ['x', 'base'], 0.8, 10) for i in range(6)]
        result = discover(discovery_rows + rows, split_month=8, min_support=3)
        rule = rule_by_itemset(result, ('x',))
        self.assertTrue(rule['simpson_conflict'])
        self.assertGreater(rule['pooled_validation']['effect'], 0)
        self.assertTrue(all(result_item['effect'] < 0
                            for result_item in rule['plant_results'].values()))

    def test_cli_discovery_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = write_csv(directory, self.records)
            output_path = Path(directory) / 'nested' / 'result.json'
            run = subprocess.run(
                [sys.executable, '-m', 'analysis_app', 'discovery',
                 '--input', str(input_path), '--output', str(output_path),
                 '--min-support', '5', '--max-order', '2'],
                text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(json.loads(output_path.read_text()), payload)
            self.assertEqual(payload['parameters']['max_order'], 2)
            self.assertTrue(all(rule['order'] <= 2 for rule in payload['rules']))

    def test_cli_rejects_invalid_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = write_csv(directory, self.records[:10])
            run = subprocess.run(
                [sys.executable, '-m', 'analysis_app', 'discovery',
                 '--input', str(input_path), '--fdr', '1.5'],
                text=True, capture_output=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn('fdr', run.stderr)


if __name__ == '__main__':
    unittest.main()
