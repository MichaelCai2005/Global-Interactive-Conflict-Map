import json
from datetime import date, timedelta

import numpy as np
import pytest

from app import risk, risk_model
from app.risk_model import Rows, auc, average_precision, backtest, fit_nb, weights_from


def test_negative_binomial_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, size=(20_000, 2))
    mu = np.exp(-1.0 + 3.0 * x[:, 0] + 1.0 * x[:, 1])
    alpha = 2.0
    # NB2 as a gamma-Poisson mixture: variance mu + alpha * mu^2.
    y = rng.poisson(rng.gamma(1 / alpha, alpha * mu)).astype(float)
    model = fit_nb(x, y)
    assert model.intercept == pytest.approx(-1.0, abs=0.1)
    assert model.coef == pytest.approx([3.0, 1.0], abs=0.1)
    assert model.alpha == pytest.approx(alpha, rel=0.15)


def test_a_part_that_fits_negative_is_dropped_so_it_cannot_lower_a_score():
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 1, size=(10_000, 2))
    y = rng.poisson(np.exp(0.5 + 2.0 * x[:, 0] - 1.5 * x[:, 1])).astype(float)
    assert fit_nb(x, y, nonneg=False).coef[1] < 0
    model = fit_nb(x, y)
    assert model.coef[1] == 0
    assert model.coef[0] > 0


def test_auc_counts_ties_as_half():
    label = np.array([1, 1, 0, 0])
    assert auc(np.array([4.0, 3, 2, 1]), label) == 1
    assert auc(np.array([1.0, 2, 3, 4]), label) == 0
    assert auc(np.ones(4), label) == 0.5
    assert auc(np.array([3.0, 1, 2, 1]), label) == pytest.approx(0.625)


def test_average_precision_does_not_credit_ties_in_a_lucky_order():
    label = np.array([1, 0, 1, 0])
    assert average_precision(np.array([4.0, 3, 2, 1]), label) == pytest.approx((1 + 2 / 3) / 2)
    # Everything tied is the base rate, whatever order the rows came in.
    assert average_precision(np.zeros(4), label) == pytest.approx(0.5)


def test_weights_share_eighty_points_and_signal_keeps_twenty():
    model = risk_model.NegBin(0.0, np.array([6.0, 2.0, 0.0]), 1.0, 0.0)
    assert weights_from(model) == {"history": 60.0, "surge": 20.0, "spread": 0.0, "signal": 20.0}


def synthetic_rows(n_countries=6, start=date(1995, 1, 2), n_weeks=52 * 10) -> Rows:
    rng = np.random.default_rng(2)
    weeks = [start + timedelta(weeks=w) for w in range(n_weeks)]
    levels = rng.uniform(0, 1, size=(n_countries * n_weeks, 3))
    mu = np.exp(-2 + 5 * levels[:, 0] + 2 * levels[:, 1])
    deaths = rng.poisson(mu).astype(float)
    return Rows(
        iso3=np.repeat([f"C{i:02}" for i in range(n_countries)], n_weeks),
        week=np.array(weeks * n_countries, dtype="datetime64[D]"),
        levels=levels,
        deaths_next=deaths,
        deaths_recent=deaths,
        deaths_prior=deaths * 6,
    )


def test_backtest_only_trains_on_outcomes_known_before_the_test_year(monkeypatch):
    rows = synthetic_rows()
    seen = []
    real_fit = risk_model.fit_nb

    def spy(x, y, nonneg=True):
        seen.append(len(y))
        return real_fit(x, y, nonneg)

    monkeypatch.setattr(risk_model, "fit_nb", spy)
    bt = backtest(rows, first_year=2000)
    assert sorted(bt.fits) == list(range(2000, 2005))
    assert len(bt.rows) == (rows.year >= 2000).sum()
    # The training set for each year holds exactly the weeks whose 4-week outcome
    # (plus the week itself) ended by 1 January of that year.
    outcome_end = rows.week + np.timedelta64(7 * (risk_model.HORIZON + 1), "D")
    expected = [
        (outcome_end <= np.datetime64(f"{y}-01-01")).sum()
        for y in range(2000, 2005)
        for _ in risk_model.CANDIDATES
    ]
    assert seen == expected
    assert all(np.isfinite(p).all() for p in bt.predicted.values())
    # The synthetic outcome follows the first two levels, so the fit finds them.
    assert bt.fits[2004].coef[0] > bt.fits[2004].coef[1] > bt.fits[2004].coef[2]


def test_report_names_every_model_and_the_known_weeks(monkeypatch):
    rows = synthetic_rows()
    monkeypatch.setattr(risk_model, "KNOWN_WEEKS", (("C00", date(1999, 1, 4), "test week"),))
    bt = backtest(rows, first_year=2003)
    text = risk_model.report(bt, fit_nb(rows.levels, rows.deaths_next), rows)
    for c in risk_model.CANDIDATES:
        assert f"| {c.name} |" in text
    assert "| C00 | 1999-01-04 | test week |" in text


def test_scoring_uses_fitted_weights_when_saved(tmp_path):
    path = tmp_path / "weights.json"
    assert risk.load_weights(path) == risk.HAND_SET_WEIGHTS
    model = risk_model.NegBin(-1.0, np.array([7.0, 2.0, 1.0]), 10.0, -1.8)
    saved = risk_model.save_weights(model, synthetic_rows(), path)
    assert json.loads(path.read_text())["weights"] == saved["weights"]
    assert risk.load_weights(path) == {
        "history": 56.0,
        "surge": 16.0,
        "spread": 8.0,
        "signal": 20.0,
    }


def test_build_rows_pairs_each_week_with_the_deaths_after_it():
    n = 70
    weeks = [date(2021, 1, 4) + timedelta(weeks=w) for w in range(n)]
    deaths = [0] * n
    deaths[60] = 30
    violent = [1 if d else 0 for d in deaths]
    data = {
        "AAA": risk.CountryWeeks(
            violent={"ucdp": violent, "acled": [0] * n},
            deaths=deaths,
            gdelt_events=[0] * n,
            goldstein=[None] * n,
            tone=[None] * n,
        ),
        # GDELT-only countries have no outcome and are left out.
        "BBB": risk.CountryWeeks(
            violent={"ucdp": [0] * n, "acled": [0] * n},
            deaths=[0] * n,
            gdelt_events=[5] * n,
            goldstein=[None] * n,
            tone=[None] * n,
        ),
    }
    # The last outcome week (week 65) is partial, so outcomes run through week 64.
    rows = risk_model.build_rows(weeks, data, {}, weeks[65])
    assert set(rows.iso3) == {"AAA"}
    assert rows.week[0] == np.datetime64(weeks[risk_model.BURN_IN])
    assert rows.week[-1] == np.datetime64(weeks[65 - risk_model.HORIZON - 1])
    by_week = {str(w): i for i, w in enumerate(rows.week)}
    assert rows.deaths_next[by_week[str(weeks[56])]] == 30  # weeks 57-60
    assert rows.deaths_next[by_week[str(weeks[55])]] == 0  # weeks 56-59
    assert rows.deaths_recent[by_week[str(weeks[60])]] == 30
    assert rows.levels[by_week[str(weeks[60])], 0] == pytest.approx(risk.death_level(30))
