"""037 概率与评估原语测试（纯函数，不涉及服务/数据库）。"""

import math
from datetime import date, timedelta

import pytest

from foot_web.engine import probability as prob


def test_poisson_pmf_sums_to_one():
    total = sum(prob.poisson_pmf(k, 1.8) for k in range(40))
    assert total == pytest.approx(1.0, abs=1e-9)


def test_score_matrix_normalises_and_matches_independent_poisson():
    matrix = prob.score_matrix(1.5, 1.1, rho=0.0)
    assert sum(sum(row) for row in matrix) == pytest.approx(1.0, abs=1e-9)
    raw = sum(prob.poisson_pmf(i, 1.5) * prob.poisson_pmf(j, 1.1)
              for i in range(prob.MAX_GOALS + 1) for j in range(prob.MAX_GOALS + 1))
    for i in range(3):
        for j in range(3):
            expected = prob.poisson_pmf(i, 1.5) * prob.poisson_pmf(j, 1.1) / raw
            assert matrix[i][j] == pytest.approx(expected, rel=1e-9)


def test_dixon_coles_tau_affects_only_low_scores():
    lam_home, lam_away, rho = 1.4, 1.1, -0.1
    assert prob.dixon_coles_tau(0, 0, lam_home, lam_away, rho) == pytest.approx(1 - lam_home * lam_away * rho)
    assert prob.dixon_coles_tau(0, 1, lam_home, lam_away, rho) == pytest.approx(1 + lam_home * rho)
    assert prob.dixon_coles_tau(1, 0, lam_home, lam_away, rho) == pytest.approx(1 + lam_away * rho)
    assert prob.dixon_coles_tau(1, 1, lam_home, lam_away, rho) == pytest.approx(1 - rho)
    assert prob.dixon_coles_tau(2, 0, lam_home, lam_away, rho) == 1.0


def test_outcome_probabilities_sum_and_symmetry():
    symmetric = prob.score_matrix(1.3, 1.3, rho=0.0)
    outcomes = prob.outcome_probabilities(symmetric)
    assert sum(outcomes.values()) == pytest.approx(1.0, abs=1e-9)
    assert outcomes['home'] == pytest.approx(outcomes['away'], rel=1e-9)
    assert outcomes['draw'] > 0


def test_total_goals_lines_include_push_only_for_integer_lines():
    matrix = prob.score_matrix(1.4, 1.2)
    half = prob.over_under_probabilities(matrix, 2.5)
    assert half['push'] == pytest.approx(0.0)
    assert half['over'] + half['under'] == pytest.approx(1.0, abs=1e-9)
    whole = prob.over_under_probabilities(matrix, 2.0)
    assert whole['push'] > 0
    assert sum(whole.values()) == pytest.approx(1.0, abs=1e-9)


def test_handicap_has_push_on_level_line():
    matrix = prob.score_matrix(1.2, 1.2, rho=0.0)
    level = prob.handicap_probabilities(matrix, 0.0)
    assert level['home'] == pytest.approx(level['away'], rel=1e-9)
    assert level['push'] == pytest.approx(prob.outcome_probabilities(matrix)['draw'], rel=1e-9)
    one = prob.handicap_probabilities(matrix, -1.0)
    assert sum(one.values()) == pytest.approx(1.0, abs=1e-9)


def test_elo_expected_and_update_direction():
    assert prob.elo_expected(1500, 1500) == pytest.approx(0.5)
    assert prob.elo_expected(1600, 1500) > 0.5
    assert prob.elo_expected(1400, 1500) < 0.5
    base = prob.elo_update(1500, 0.5, 1.0, goal_diff=1)
    assert base > 1500
    assert prob.elo_update(1500, 0.5, 0.0) < 1500
    assert prob.elo_update(1500, 0.5, 1.0, goal_diff=3) > base


def test_metrics_basic_properties():
    assert prob.log_loss([1.0, 0.0], [1, 0]) < 1e-9
    assert prob.brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert prob.log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))
    assert prob.brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)
    assert 0 <= prob.expected_calibration_error([0.2] * 10 + [0.8] * 10, [0] * 8 + [1] * 2 + [1] * 8 + [0] * 2) <= 1


def test_calibration_slope_recovers_synthetic_relationship():
    probabilities, outcomes = [], []
    for i in range(3000):
        x = (i / 2999) * 6 - 3
        p = 1 / (1 + math.exp(-(0.3 + 0.8 * x)))
        probabilities.append(p)
        outcomes.append(1 if ((i * 0.61803398875) % 1) < p else 0)
    slope = prob.calibration_slope(probabilities, outcomes)
    assert 0.3 < slope < 1.8


def test_walk_forward_splits_are_disjoint_and_ordered():
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=i) for i in range(60)]
    splits = prob.walk_forward_splits(dates, train=20, calibrate=5, test=10, embargo=2)
    assert len(splits) >= 2
    assert splits[0]['test'][0] > splits[0]['calibrate'][-1]
    for split in splits:
        assert len(split['train']) == 20
        assert len(split['calibrate']) == 5
        assert len(split['test']) == 10
    for previous, current in zip(splits, splits[1:]):
        assert current['train'][0] > previous['train'][0]
        assert set(previous['test']) & set(current['test']) == set()
    assert prob.walk_forward_splits(dates[:30], 20, 5, 10, 2) == []


def test_invalid_arguments_are_rejected():
    matrix = prob.score_matrix(1.2, 1.0)
    with pytest.raises(ValueError):
        prob.over_under_probabilities(matrix, 2.25)
    with pytest.raises(ValueError):
        prob.handicap_probabilities(matrix, 0.75)
    with pytest.raises(ValueError):
        prob.log_loss([0.5], [1, 0])
    with pytest.raises(ValueError):
        prob.calibration_slope([0.5] * 10, [0, 1] * 5)
    with pytest.raises(ValueError):
        prob.score_matrix(-1.0, 1.0)
