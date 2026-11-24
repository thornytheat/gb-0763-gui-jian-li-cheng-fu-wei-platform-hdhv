def _bounds(intervals):
    for item in intervals:
        lo, hi = item
        if lo < hi:
            yield lo, hi


def union(intervals):
    """合并区间为互不相交的半开区间并集，相接区间合并，空区间忽略。"""
    merged = []
    for lo, hi in sorted(_bounds(intervals)):
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    return merged


def intersect(left, right):
    """两个已合并区间列表的交集。"""
    overlap, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        lo = max(left[i][0], right[j][0])
        hi = min(left[i][1], right[j][1])
        if lo < hi:
            overlap.append([lo, hi])
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return overlap


def subtract(base, covered):
    """从已合并的 base 区间中扣除 covered（同样已合并）覆盖的部分。"""
    remainder = []
    for lo, hi in base:
        cursor = lo
        for c_lo, c_hi in covered:
            if c_hi <= cursor:
                continue
            if c_lo >= hi:
                break
            if c_lo > cursor:
                remainder.append([cursor, min(c_lo, hi)])
            cursor = max(cursor, c_hi)
            if cursor >= hi:
                break
        if cursor < hi:
            remainder.append([cursor, hi])
    return remainder


def length(intervals):
    return sum(hi - lo for lo, hi in intervals)
