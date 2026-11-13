"""验证期统计：厂内条件关联、双侧 z 检验与 BH 校正。

size 仅作为良率均值的权重出现。加权两样本比较使用正态近似的 z 统计量：
组内方差按 size 加权的良率离差估计，有效样本量为权重总和；
批次极少时不做检验（不可检验），避免给出过度自信的 p 值。
"""
import math


def weighted_stats(transactions):
    """返回 (加权均值, 权重合计, 批次数)；权重为 0 或空集时均值为 None。"""
    weight = sum(t['size'] for t in transactions)
    count = len(transactions)
    if weight <= 0:
        return None, weight, count
    mean = math.fsum(t['weighted_yield'] * t['size']
                     for t in transactions if t['weighted_yield'] is not None) / weight
    return mean, weight, count


def _weighted_variance(transactions, mean):
    """加权方差（可靠性权重口径），有效样本量取权重合计。"""
    weight = math.fsum(t['size'] for t in transactions)
    if weight <= 0 or mean is None:
        return None, weight
    variance = math.fsum(t['size'] * (t['weighted_yield'] - mean) ** 2
                         for t in transactions if t['weighted_yield'] is not None) / weight
    return variance, weight


def normal_sf_two_sided(z_score):
    """双侧正态生存函数 2*(1-Phi(|z|))，标准库 erf 实现。"""
    return math.erfc(abs(z_score) / math.sqrt(2.0))


def compare_groups(present, absent, min_lots):
    """同一工厂内规则命中组与未命中组的加权良率对比。

    任一组批次数低于 min_lots 时返回 testable=False，不产生 p 值。
    """
    mean_p, weight_p, count_p = weighted_stats(present)
    mean_a, weight_a, count_a = weighted_stats(absent)
    result = {
        'testable': False
        if (count_p < min_lots or count_a < min_lots
            or mean_p is None or mean_a is None) else True,
        'present_lots': count_p,
        'absent_lots': count_a,
        'present_weighted_yield': mean_p,
        'absent_weighted_yield': mean_a,
        'effect': None,
        'z_score': None,
        'p_value': None,
        'zero_variance': False,
    }
    if not result['testable']:
        return result
    var_p, _ = _weighted_variance(present, mean_p)
    var_a, _ = _weighted_variance(absent, mean_a)
    effect = mean_p - mean_a
    result['effect'] = effect
    standard_error = math.sqrt(var_p / weight_p + var_a / weight_a)
    if standard_error <= 0.0:
        # 零方差（例如组内良率完全相同）：z 不可定义，避免输出不可序列化的 inf；
        # 效应非零记为极端显著 p=0，效应为零记为 p=1，并显式标记退化情形。
        result['zero_variance'] = True
        result['p_value'] = 1.0 if effect == 0.0 else 0.0
        return result
    z_score = effect / standard_error
    result['z_score'] = z_score
    result['p_value'] = normal_sf_two_sided(z_score)
    return result


def benjamini_hochberg(p_values):
    """BH 逐步校正。输入 (key, p) 序列，返回 {key: 调整后 p 值}。

    检验族边界由调用方确定：这里只对传入的、事先声明可检验的假设做校正，
    不接收事后挑选的分厂结果。等秩 p 值取同一调整值，调整值在阶内单调。
    """
    ordered = sorted(p_values, key=lambda entry: (entry[1], str(entry[0])))
    total = len(ordered)
    adjusted = {}
    running = 1.0
    for rank_from_end in range(total, 0, -1):
        key, p_value = ordered[rank_from_end - 1]
        value = min(running, p_value * total / rank_from_end)
        running = value
        adjusted[key] = min(1.0, value)
    return adjusted
