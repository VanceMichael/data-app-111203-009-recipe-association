import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .discovery import (DEFAULT_FDR, DEFAULT_MAX_CANDIDATE_SETS,
                        DEFAULT_MAX_ORDER, DEFAULT_MIN_LOTS_PER_GROUP,
                        DEFAULT_MIN_SUPPORT, DEFAULT_SPLIT_MONTH, discover)
from .io import load_records
from .summary import summarize


def save_json(path, result):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.analysis-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description='本地观测数据分析')
    commands = parser.add_subparsers(dest='command', required=True)
    summary = commands.add_parser('summary', help='按业务维度核对观测口径')
    summary.add_argument('--input', type=Path, default=Path('data/observations.csv'))
    summary.add_argument('--output', type=Path)

    discovery_parser = commands.add_parser(
        'discovery', help='发现期筛选规则、验证期厂内复验，形成复验候选')
    discovery_parser.add_argument('--input', type=Path,
                                  default=Path('data/observations.csv'))
    discovery_parser.add_argument('--output', type=Path)
    discovery_parser.add_argument('--split-month', type=int,
                                  default=DEFAULT_SPLIT_MONTH)
    discovery_parser.add_argument('--min-support', type=int,
                                  default=DEFAULT_MIN_SUPPORT)
    discovery_parser.add_argument('--max-order', type=int,
                                  default=DEFAULT_MAX_ORDER)
    discovery_parser.add_argument('--max-candidate-sets', type=int,
                                  default=DEFAULT_MAX_CANDIDATE_SETS)
    discovery_parser.add_argument('--min-lots-per-group', type=int,
                                  default=DEFAULT_MIN_LOTS_PER_GROUP)
    discovery_parser.add_argument('--fdr', type=float, default=DEFAULT_FDR)
    args = parser.parse_args()
    try:
        if args.command == 'summary':
            result = summarize(load_records(args.input))
        else:
            for name, value in (('--min-support', args.min_support),
                                ('--max-order', args.max_order),
                                ('--max-candidate-sets', args.max_candidate_sets),
                                ('--min-lots-per-group', args.min_lots_per_group)):
                if value < 1:
                    raise ValueError(f'{name} 必须为不小于 1 的整数')
            if not 0.0 < args.fdr < 1.0:
                raise ValueError('--fdr 必须位于 (0, 1) 区间')
            result = discover(
                load_records(args.input),
                split_month=args.split_month,
                min_support=args.min_support,
                max_order=args.max_order,
                max_candidate_sets=args.max_candidate_sets,
                min_lots_per_group=args.min_lots_per_group,
                fdr=args.fdr)
        if args.output:
            save_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
