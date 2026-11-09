"""概率与评估原语（规格037）。

借鉴 Dixon-Coles / Poisson / Elo 的公开实现方法，用于后续评测与模型就绪验收。
本模块是**纯函数库**：不读网络、不读数据库、不写任何工件，也**没有接入推荐、
发布或复盘链路**。在 027 的预注册外样本门槛通过前，产品中的 `model_probability`
与 `EV` 必须保持 null，不得用本模块结果冒充模型胜率。

来源与许可见 docs/open-source-borrowing.md。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

MAX_GOALS = 10
_EPS = 1e-12


def poisson_pmf(k: int, lam: float) -> float:
    """Poisson 概率质量函数 P(X=k)。"""
    if k < 0:
        raise ValueError('k 必须非负')
    if lam < 0:
        raise ValueError('lam 必须非负')
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def dixon_coles_tau(home_goals: int, away_goals: int, lam_home: float, lam_away: float, rho: float) -> float:
    """Dixon-Coles 低比分相关修正系数，仅影响 0:0、1:0、0:1、1:1。"""
    if (home_goals, away_goals) == (0, 0):
        return 1.0 - lam_home * lam_away * rho
    if (home_goals, away_goals) == (0, 1):
        return 1.0 + lam_home * rho
    if (home_goals, away_goals) == (1, 0):
        return 1.0 + lam_away * rho
    if (home_goals, away_goals) == (1, 1):
        return 1.0 - rho
    return 1.0


def score_matrix(lam_home: float, lam_away: float, rho: float = 0.0,
                 max_goals: int = MAX_GOALS) -> list[list[float]]:
    """归一化比分矩阵，matrix[i][j] 为主队 i 球、客队 j 球的概率。

    max_goals 之外的概率被截断并重新归一化；返回值各行长度一致。
    """
    if max_goals < 1:
        raise ValueError('max_goals 必须为正整数')
    if lam_home < 0 or lam_away < 0:
        raise ValueError('进球期望必须非负')
    raw = [
        [poisson_pmf(i, lam_home) * poisson_pmf(j, lam_away)
         * dixon_coles_tau(i, j, lam_home, lam_away, rho) for j in range(max_goals + 1)]
        for i in range(max_goals + 1)
    ]
    if any(value < 0 for row in raw for value in row):
        raise ValueError('rho 取值使修正系数为负，请检查参数范围')
    total = sum(value for row in raw for value in row)
    if total <= 0:
        raise ValueError('比分矩阵总概率为零')
    return [[value / total for value in row] for row in raw]


def outcome_probabilities(matrix: Sequence[Sequence[float]]) -> dict[str, float]:
    """胜平负概率，主队在前。"""
    home = draw = away = 0.0
    for i, row in enumerate(matrix):
        for j, probability in enumerate(row):
            if i > j:
                home += probability
            elif i == j:
                draw += probability
            else:
                away += probability
    return {'home': home, 'draw': draw, 'away': away}


def total_goals_distribution(matrix: Sequence[Sequence[float]]) -> list[float]:
    """总进球分布，索引即总进球数。"""
    size = sum(len(row) for row in matrix)
    distribution = [0.0] * size
    for i, row in enumerate(matrix):
        for j, probability in enumerate(row):
            distribution[i + j] += probability
    return distribution


def _is_supported_line(line: float) -> bool:
    doubled = line * 2
    return math.isclose(doubled, round(doubled), abs_tol=1e-9)


def over_under_probabilities(matrix: Sequence[Sequence[float]], line: float) -> dict[str, float]:
    """总进球大小球，支持整球线与半球线；四分之一球线不支持。

    返回 {'over': 大, 'push': 走水, 'under': 小}，三者和为 1。
    """
    if not _is_supported_line(line):
        raise ValueError('暂只支持整球线与半球线')
    over = push = under = 0.0
    distribution = total_goals_distribution(matrix)
    for total, probability in enumerate(distribution):
        if total > line:
            over += probability
        elif total == line:
            push += probability
        else:
            under += probability
    return {'over': over, 'push': push, 'under': under}


def handicap_probabilities(matrix: Sequence[Sequence[float]], line: float) -> dict[str, float]:
    """主队让球结算概率，line 为主队让球数（-1 表示主让一球）。

    返回 {'home': 主赢盘, 'push': 走水, 'away': 客赢盘}。
    """
    if not _is_supported_line(line):
        raise ValueError('暂只支持整球线与半球线')
    home = push = away = 0.0
    for i, row in enumerate(matrix):
        for j, probability in enumerate(row):
            margin = (i - j) + line
            if margin > 0:
                home += probability
            elif margin == 0:
                push += probability
            else:
                away += probability
    return {'home': home, 'push': push, 'away': away}


def elo_expected(rating: float, opponent: float, home_advantage: float = 0.0) -> float:
    """Elo 期望得分，home_advantage 计入主队评分。"""
    return 1.0 / (1.0 + 10 ** ((opponent - rating - home_advantage) / 400.0))


def elo_update(rating: float, expected: float, score: float, k: float = 20.0,
               goal_diff: int = 0) -> float:
    """Elo 更新；净胜球乘数沿用常见做法（1、1.5、(11+净胜)/8）。"""
    if not 0.0 <= score <= 1.0:
        raise ValueError('score 必须在 [0,1]')
    if k <= 0:
        raise ValueError('k 必须为正')
    goal_diff = abs(goal_diff)
    if goal_diff <= 1:
        multiplier = 1.0
    elif goal_diff == 2:
        multiplier = 1.5
    else:
        multiplier = (11.0 + goal_diff) / 8.0
    return rating + k * multiplier * (score - expected)


def log_loss(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    """二元 logloss；outcomes 为 0/1。"""
    _check_pairs(probabilities, outcomes)
    total = 0.0
    for probability, outcome in zip(probabilities, outcomes):
        probability = min(max(probability, _EPS), 1.0 - _EPS)
        total += -(outcome * math.log(probability) + (1 - outcome) * math.log(1.0 - probability))
    return total / len(probabilities)


def brier_score(probabilities: Sequence[float], outcomes: Sequence[int]) -> float:
    """二元 Brier 分数。"""
    _check_pairs(probabilities, outcomes)
    return sum((probability - outcome) ** 2
               for probability, outcome in zip(probabilities, outcomes)) / len(probabilities)


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int],
                               bins: int = 10) -> float:
    """等宽分箱 ECE；概率越界视为参数错误。"""
    if bins < 1:
        raise ValueError('bins 必须为正整数')
    _check_pairs(probabilities, outcomes)
    counts = [0] * bins
    sums = [0.0] * bins
    positives = [0] * bins
    for probability, outcome in zip(probabilities, outcomes):
        if not 0.0 <= probability <= 1.0:
            raise ValueError('概率必须在 [0,1]')
        index = min(int(probability * bins), bins - 1)
        counts[index] += 1
        sums[index] += probability
        positives[index] += outcome
    total = len(probabilities)
    return sum(abs(sums[i] / counts[i] - positives[i] / counts[i]) * counts[i] / total
               for i in range(bins) if counts[i])


def calibration_slope(probabilities: Sequence[float], outcomes: Sequence[int],
                      iterations: int = 100, tolerance: float = 1e-9) -> float:
    """校准斜率：对 logit(p) 做 logistic 回归，返回斜率 b。

    b≈1 表示校准良好，b>1 表示预测过于保守，b<1 表示过于自信。
    """
    _check_pairs(probabilities, outcomes)
    xs = [math.log(min(max(p, _EPS), 1 - _EPS) / (1 - min(max(p, _EPS), 1 - _EPS)))
          for p in probabilities]
    if len(set(xs)) < 2:
        raise ValueError('概率无变异，无法估计校准斜率')
    a, b = 0.0, 1.0
    for _ in range(iterations):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for x, y in zip(xs, outcomes):
            fitted = _sigmoid(a + b * x)
            weight = fitted * (1.0 - fitted)
            g_a += fitted - y
            g_b += (fitted - y) * x
            h_aa += weight
            h_ab += weight * x
            h_bb += weight * x * x
        determinant = h_aa * h_bb - h_ab * h_ab
        if abs(determinant) < 1e-12:
            raise ValueError('校准拟合退化')
        step_a = (h_bb * g_a - h_ab * g_b) / determinant
        step_b = (h_aa * g_b - h_ab * g_a) / determinant
        a -= step_a
        b -= step_b
        if max(abs(step_a), abs(step_b)) < tolerance:
            break
    return b


def walk_forward_splits(dates: Sequence, train: int, calibrate: int, test: int,
                        embargo: int = 0) -> list[dict[str, list]]:
    """滚动时间切分，返回 train/calibrate/test 三段日期列表。

    每个窗口按 test 长度向前滚动；embargo 为校准与测试之间的隔离天数。
    """
    for name, value in (('train', train), ('calibrate', calibrate), ('test', test)):
        if value < 1:
            raise ValueError(f'{name} 段长度必须为正整数')
    if embargo < 0:
        raise ValueError('embargo 不能为负')
    unique = sorted({str(day) for day in dates})
    window = train + calibrate + embargo + test
    if len(unique) < window:
        return []
    splits = []
    start = 0
    while start + window <= len(unique):
        splits.append({
            'train': unique[start:start + train],
            'calibrate': unique[start + train:start + train + calibrate],
            'test': unique[start + train + calibrate + embargo:start + window],
        })
        start += test
    return splits


def _sigmoid(value: float) -> float:
    if value >= 700:
        return 1.0
    if value <= -700:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _check_pairs(probabilities: Sequence[float], outcomes: Sequence[int]) -> None:
    if not probabilities or len(probabilities) != len(outcomes):
        raise ValueError('概率与结果必须非空且等长')
    if any(outcome not in (0, 1) for outcome in outcomes):
        raise ValueError('outcomes 只能为 0 或 1')
