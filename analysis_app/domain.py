import math
import statistics
from collections import Counter


def describe(records):
    size = sum(row['size'] for row in records)
    return {'lot_count': len({row['lot'] for row in records}), 'tested_units': size, 'weighted_yield': math.fsum(row['yield_rate'] * row['size'] for row in records) / size if size else None}
