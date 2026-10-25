"""Fit the weights of the weekly risk score to what came next, and backtest them.

The score (app.risk) adds four parts whose weights were first set by hand. This module fits
them to what the score is meant to warn of, deaths in the following four weeks, and tests
the result the way it would have been used: every year is scored with weights fitted only
on earlier years (a rolling origin), so no week ever informs its own weights.

The model is the negative binomial regression the design doc names:

    log E[deaths in weeks t+1..t+4] = b0 + b_history * History + b_surge * Surge + b_spread * Spread

where each part is its 0-1 level from app.risk. With a log link, a part's coefficient says
how many times a full level of it multiplies expected deaths (e^b), and the weights are the
coefficients scaled to the points they share. The score is still a sum of parts, and still
moves in step with the log of expected deaths. Coefficients are kept non-negative (a part
that fits below zero is dropped and the rest refitted), so a part can never lower a score.

Signal is not fitted. GDELT is loaded for a handful of weeks, too few to fit or test, so it
keeps its hand-set 20 points (used only in weeks it has data) and the fitted parts share 80.

  python -m app.risk_model backtest   rolling-origin test of fitted against hand-set weights
  python -m app.risk_model fit        fit on every complete week, write app/data/risk_weights.json

Then `python -m app.risk build` scores with the new weights. Needs numpy: pip install -e ".[model]".
"""

import argparse
import json
import logging
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from app import risk

log = logging.getLogger(__name__)

FITTED = ("history", "surge", "spread")
HORIZON = 4
# UCDP counts a conflict as active from 25 battle deaths a year; 25 in a month is a war-level month.
ACTIVE_DEATHS = 25
# A country is quiet when it had fewer than ACTIVE_DEATHS deaths over the last QUIET_WEEKS.
QUIET_WEEKS = 26
# Weeks skipped at the start, so History has filled up and Surge has a baseline.
BURN_IN = 52
FIRST_TEST_YEAR = 2000
SIGNAL_POINTS = 20.0
KNOWN_WEEKS = (
    ("UKR", date(2022, 2, 28), "Russia invades Ukraine"),
    ("ISR", date(2023, 10, 9), "Hamas attack and war in Gaza"),
    ("LBN", date(2023, 10, 9), "Hezbollah opens a second front"),
    ("SDN", date(2023, 4, 17), "SAF and RSF war in Khartoum"),
    ("ETH", date(2020, 11, 2), "Tigray war begins"),
    ("MMR", date(2021, 1, 25), "week before the coup"),
)


@dataclass
class Rows:
    """One row per country-week whose next HORIZON weeks are fully covered by UCDP or ACLED."""

    iso3: np.ndarray
    week: np.ndarray  # datetime64[D]
    levels: np.ndarray  # n x 3, the 0-1 level of each FITTED part
    deaths_next: np.ndarray  # deaths in weeks t+1..t+HORIZON, the outcome
    deaths_recent: np.ndarray  # deaths in weeks t-3..t
    deaths_prior: np.ndarray  # deaths in weeks t-25..t

    @property
    def year(self) -> np.ndarray:
        return self.week.astype("datetime64[Y]").astype(int) + 1970

    def __len__(self) -> int:
        return len(self.iso3)

    def take(self, mask: np.ndarray) -> "Rows":
        return Rows(*(getattr(self, f)[mask] for f in self.__dataclass_fields__))


def build_rows(
    weeks: Sequence[date],
    data: dict[str, risk.CountryWeeks],
    neighbours: dict[str, set[str]],
    provisional_after: date | None,
    half_life: float = risk.HALF_LIFE_WEEKS,
) -> Rows:
    """Score every country-week with app.risk and pair it with the deaths that followed.

    Countries with no UCDP or ACLED event at all are left out: every model ranks them last,
    and their many empty weeks would only flatter the scores.
    """
    scored = risk.score_countries(weeks, data, neighbours, provisional_after, half_life)
    by_country: dict[str, list[risk.ScoreRow]] = defaultdict(list)
    for r in scored:
        by_country[r.iso3].append(r)
    # Outcomes stop with the last week the hand-coded sources wholly cover.
    end = weeks.index(provisional_after) + 1 if provisional_after in weeks else len(weeks)
    last = end - HORIZON - 1
    cols: dict[str, list] = defaultdict(list)
    for c in sorted(by_country):
        d = data[c]
        if not any(any(v) for v in d.violent.values()):
            continue
        cum = np.concatenate([[0], np.cumsum(d.deaths)])
        for t in range(BURN_IN, last + 1):
            r = by_country[c][t]
            cols["iso3"].append(c)
            cols["week"].append(weeks[t])
            cols["levels"].append([r.level[p] for p in FITTED])
            cols["deaths_next"].append(cum[t + 1 + HORIZON] - cum[t + 1])
            cols["deaths_recent"].append(cum[t + 1] - cum[max(t - 3, 0)])
            cols["deaths_prior"].append(cum[t + 1] - cum[max(t - QUIET_WEEKS + 1, 0)])
    return Rows(
        iso3=np.array(cols["iso3"]),
        week=np.array(cols["week"], dtype="datetime64[D]"),
        levels=np.array(cols["levels"], dtype=float).reshape(-1, len(FITTED)),
        deaths_next=np.array(cols["deaths_next"], dtype=float),
        deaths_recent=np.array(cols["deaths_recent"], dtype=float),
        deaths_prior=np.array(cols["deaths_prior"], dtype=float),
    )


# --- Negative binomial regression -----------------------------------------------------------

_lgamma = np.frompyfunc(math.lgamma, 1, 1)


@dataclass
class NegBin:
    """NB2 regression: log mu = intercept + X @ coef, variance mu + alpha * mu^2."""

    intercept: float
    coef: np.ndarray
    alpha: float
    loglik: float  # mean per row on the data it was fitted to

    def mu(self, x: np.ndarray) -> np.ndarray:
        return np.exp(np.clip(self.intercept + x @ self.coef, -50, 50))

    def loglik_of(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return nb_loglik(y, self.mu(x), self.alpha)


def nb_loglik(y: np.ndarray, mu: np.ndarray, alpha: float) -> np.ndarray:
    """Log-likelihood of each count under NB2 with mean mu and dispersion alpha."""
    r = 1.0 / alpha
    out = -r * np.log1p(alpha * mu)
    pos = y > 0
    yp, mp = y[pos], mu[pos]
    out[pos] += (
        (_lgamma(yp + r) - _lgamma(yp + 1.0)).astype(float)
        - math.lgamma(r)
        + yp * (np.log(alpha * mp) - np.log1p(alpha * mp))
    )
    return out


def _fit_beta(x1: np.ndarray, y: np.ndarray, alpha: float, beta: np.ndarray) -> np.ndarray:
    """Coefficients for a fixed alpha, by Fisher scoring with step halving."""

    def ll(b):
        return nb_loglik(y, np.exp(np.clip(x1 @ b, -50, 50)), alpha).sum()

    current = ll(beta)
    for _ in range(100):
        mu = np.exp(np.clip(x1 @ beta, -50, 50))
        grad = x1.T @ ((y - mu) / (1 + alpha * mu))
        info = (x1 * (mu / (1 + alpha * mu))[:, None]).T @ x1
        step = np.linalg.solve(info + 1e-9 * np.eye(len(beta)), grad)
        for _ in range(30):
            trial = ll(beta + step)
            if trial >= current - 1e-9:
                break
            step /= 2
        beta, gain, current = beta + step, trial - current, trial
        if np.abs(step).max() < 1e-7 or abs(gain) < 1e-9 * max(1.0, abs(current)):
            break
    return beta


def _fit_unconstrained(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, float]:
    x1 = np.column_stack([np.ones(len(y)), x])
    beta = np.zeros(x1.shape[1])
    beta[0] = math.log(max(y.mean(), 1e-6))
    # Golden-section search for alpha on a log scale, refitting the coefficients each time.
    lo, hi = math.log(1e-3), math.log(1e4)
    g = (math.sqrt(5) - 1) / 2
    cache: dict[float, tuple[float, np.ndarray]] = {}

    def profile(log_alpha: float) -> float:
        nonlocal beta
        if log_alpha not in cache:
            beta = _fit_beta(x1, y, math.exp(log_alpha), beta)
            ll = nb_loglik(y, np.exp(np.clip(x1 @ beta, -50, 50)), math.exp(log_alpha)).sum()
            cache[log_alpha] = (ll, beta.copy())
        return cache[log_alpha][0]

    a, b = hi - g * (hi - lo), lo + g * (hi - lo)
    while hi - lo > 1e-3:
        if profile(a) > profile(b):
            hi, b = b, a
            a = hi - g * (hi - lo)
        else:
            lo, a = a, b
            b = lo + g * (hi - lo)
    best = max(cache, key=lambda k: cache[k][0])
    ll, beta = cache[best]
    return beta, math.exp(best), ll / len(y)


def fit_nb(x: np.ndarray, y: np.ndarray, nonneg: bool = True) -> NegBin:
    """Fit NB2 by maximum likelihood. With nonneg, a column fitting below zero is dropped
    (its coefficient fixed at 0) and the rest refitted, until none is negative."""
    x = np.asarray(x, dtype=float).reshape(len(y), -1)
    keep = list(range(x.shape[1]))
    while True:
        beta, alpha, ll = _fit_unconstrained(x[:, keep], y)
        coef = np.zeros(x.shape[1])
        coef[keep] = beta[1:]
        negative = [j for j in keep if coef[j] < 0]
        if not nonneg or not negative:
            return NegBin(float(beta[0]), coef, alpha, ll)
        keep.remove(min(negative, key=lambda j: coef[j]))
        if not keep:
            beta, alpha, ll = _fit_unconstrained(np.zeros((len(y), 0)), y)
            return NegBin(float(beta[0]), np.zeros(x.shape[1]), alpha, ll)


# --- Ranking metrics ---------------------------------------------------------------------------


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Chance a random positive outranks a random negative, ties counting half."""
    label = label.astype(bool)
    n_pos, n_neg = label.sum(), (~label).sum()
    if not n_pos or not n_neg:
        return float("nan")
    _, inverse, counts = np.unique(score, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    ranks = (ends - (counts - 1) / 2)[inverse]  # average rank of each tie group, from 1
    return float((ranks[label].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def average_precision(score: np.ndarray, label: np.ndarray) -> float:
    """Area under the precision-recall curve, stepping once per distinct score so ties
    are not credited in an arbitrary order."""
    label = label.astype(bool)
    if not label.any():
        return float("nan")
    order = np.argsort(-score, kind="stable")
    s, lab = score[order], label[order]
    last_of_group = np.r_[s[1:] != s[:-1], True]
    tp = np.cumsum(lab)[last_of_group]
    seen = np.arange(1, len(s) + 1)[last_of_group]
    recall = tp / label.sum()
    precision = tp / seen
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


# --- Models compared in the backtest -----------------------------------------------------------

HAND_SET = np.array([risk.HAND_SET_WEIGHTS[p] for p in FITTED])


@dataclass
class Candidate:
    name: str
    features: Callable[[Rows], np.ndarray]
    note: str


CANDIDATES = (
    Candidate(
        "Fitted weights",
        lambda r: r.levels,
        "History, Surge and Spread weighted by the NB coefficients",
    ),
    Candidate(
        "Hand-set weights",
        lambda r: r.levels @ HAND_SET / HAND_SET.sum(),
        "the original 40/20/20 score (the model only sets its scale)",
    ),
    Candidate("History only", lambda r: r.levels[:, :1], "decayed deaths alone"),
    Candidate(
        "Last 4 weeks",
        lambda r: np.log1p(r.deaths_recent),
        "naive baseline: next month looks like the last",
    ),
)


@dataclass
class Backtest:
    rows: Rows
    predicted: dict[str, np.ndarray]  # out-of-sample expected deaths per candidate
    loglik: dict[str, np.ndarray]  # out-of-sample log-likelihood per row
    fits: dict[int, NegBin]  # the fitted-weights model for each test year


def backtest(rows: Rows, first_year: int = FIRST_TEST_YEAR) -> Backtest:
    """Score each year from first_year on with models fitted only on weeks whose outcome
    was complete before that year began."""
    years = rows.year
    outcome_end = rows.week + np.timedelta64(7 * (HORIZON + 1), "D")
    test = years >= first_year
    out = rows.take(test)
    predicted = {c.name: np.zeros(len(out)) for c in CANDIDATES}
    loglik = {c.name: np.zeros(len(out)) for c in CANDIDATES}
    fits: dict[int, NegBin] = {}
    for year in sorted(set(years[test])):
        cutoff = np.datetime64(f"{year}-01-01")
        train = rows.take(outcome_end <= cutoff)
        here = out.year == year
        held = out.take(here)
        for c in CANDIDATES:
            model = fit_nb(c.features(train), train.deaths_next)
            x = c.features(held).reshape(len(held), -1)
            predicted[c.name][here] = model.mu(x)
            loglik[c.name][here] = model.loglik_of(x, held.deaths_next)
            if c.name == "Fitted weights":
                fits[year] = model
        log.info("backtest %d: %d training rows, %d test rows", year, len(train), len(held))
    return Backtest(out, predicted, loglik, fits)


def weights_from(model: NegBin) -> dict[str, float]:
    """Points per part: the fitted coefficients share 100 - SIGNAL_POINTS in proportion."""
    total = model.coef.sum()
    share = model.coef / total if total > 0 else HAND_SET / HAND_SET.sum()
    points = {
        p: round(float(s * (100 - SIGNAL_POINTS)), 1) for p, s in zip(FITTED, share, strict=True)
    }
    return points | {"signal": SIGNAL_POINTS}


def score_with(levels: np.ndarray, weights: dict[str, float]) -> np.ndarray:
    """The score from the FITTED parts alone, as in weeks without GDELT data."""
    w = np.array([weights[p] for p in FITTED])
    return 100 * levels @ w / w.sum()


# --- Report ------------------------------------------------------------------------------------


def report(bt: Backtest, final: NegBin, all_rows: Rows) -> str:
    rows = bt.rows
    active = rows.deaths_next >= ACTIVE_DEATHS
    quiet = rows.deaths_prior < ACTIVE_DEATHS
    years = sorted(bt.fits)
    lines = [
        f"Rolling-origin backtest, {years[0]}-{years[-1]}: each year scored with models fitted "
        "on earlier years only.",
        f"{len(rows):,} country-weeks in {len(set(rows.iso3))} countries. Outcome: UCDP/ACLED "
        f"deaths in the next {HORIZON} weeks.",
        f"'Any': predict {ACTIVE_DEATHS}+ deaths next {HORIZON} weeks "
        f"({active.sum():,} of {len(rows):,} weeks).",
        f"'Flare-up': the same, only in countries with under {ACTIVE_DEATHS} deaths in the last "
        f"{QUIET_WEEKS} weeks ({(active & quiet).sum():,} of {quiet.sum():,} weeks).",
        "",
        "| Model | Any AUC | Any AP | Flare-up AUC | Flare-up AP | Log-lik / week |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in CANDIDATES:
        p = bt.predicted[c.name]
        lines.append(
            f"| {c.name} | {auc(p, active):.3f} | {average_precision(p, active):.3f} | "
            f"{auc(p[quiet], active[quiet]):.3f} | "
            f"{average_precision(p[quiet], active[quiet]):.3f} | "
            f"{bt.loglik[c.name].mean():.3f} |"
        )
    lines += [
        "",
        "AUC: chance a week that turned violent outranked one that didn't (0.5 is a coin flip). "
        "AP: average precision, which rewards putting the violent weeks at the very top. "
        "Log-likelihood: how probable the model found the deaths that happened (higher is better).",
        "",
        "Top of the list: share of each week's 10 highest-ranked countries that had "
        f"{ACTIVE_DEATHS}+ deaths in the next {HORIZON} weeks.",
        "",
        "| Model | Precision in top 10 |",
        "| --- | --- |",
    ]
    for c in CANDIDATES:
        lines.append(f"| {c.name} | {top_k_precision(rows, bt.predicted[c.name], active):.3f} |")

    lines += ["", "Weights fitted at each origin (points of 80, Signal keeps 20):", ""]
    lines += ["| Test year | History | Surge | Spread | alpha |", "| --- | --- | --- | --- | --- |"]
    for y in sorted(set(years[::2]) | {years[-1]}):
        w = weights_from(bt.fits[y])
        lines.append(
            f"| {y} | {w['history']:.1f} | {w['surge']:.1f} | {w['spread']:.1f} | "
            f"{bt.fits[y].alpha:.1f} |"
        )

    weights = weights_from(final)
    oos = np.zeros(len(rows))
    for y, m in bt.fits.items():
        here = rows.year == y
        oos[here] = score_with(rows.levels[here], weights_from(m))
    lines += [
        "",
        "Calibration, out of sample: what followed weeks in each score band (fitted weights, "
        "weeks without GDELT).",
        "",
        f"| Score | Weeks | Share with {ACTIVE_DEATHS}+ deaths next {HORIZON} wks | Median deaths "
        f"| Mean deaths |",
        "| --- | --- | --- | --- | --- |",
    ]
    for lo in range(0, 100, 10):
        band = (oos >= lo) & (oos < lo + 10 if lo < 90 else oos <= 100)
        if band.any():
            d = rows.deaths_next[band]
            lines.append(
                f"| {lo}-{lo + 10} | {band.sum():,} | {(d >= ACTIVE_DEATHS).mean():.1%} | "
                f"{np.median(d):,.0f} | {d.mean():,.0f} |"
            )

    total = final.coef.sum()
    lines += [
        "",
        f"Final fit on all {len(all_rows):,} complete weeks: intercept {final.intercept:.2f}, "
        f"alpha {final.alpha:.2f}, coefficients "
        + ", ".join(f"{p} {b:.2f}" for p, b in zip(FITTED, final.coef, strict=True))
        + f". Weights: History {weights['history']}, Surge {weights['surge']}, "
        f"Spread {weights['spread']}, Signal {weights['signal']} (hand-set).",
        f"In a week without GDELT, each 10 points multiplies expected deaths by "
        f"{math.exp(total / 10):.2f}; a score of 0 expects {math.exp(final.intercept):.1f} deaths "
        f"in the next {HORIZON} weeks and 100 expects {math.exp(final.intercept + total):,.0f}.",
        "",
        "Known weeks (final weights; scores without Signal):",
        "",
        f"| Country | Week | Event | Hand-set | Fitted | Deaths next {HORIZON} wks |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    hand = dict(zip(FITTED, HAND_SET, strict=True))
    for iso3, week, what in KNOWN_WEEKS:
        hit = (all_rows.iso3 == iso3) & (all_rows.week == np.datetime64(week))
        if hit.any():
            lv = all_rows.levels[hit]
            lines.append(
                f"| {iso3} | {week} | {what} | {score_with(lv, hand)[0]:.0f} | "
                f"{score_with(lv, weights)[0]:.0f} | {all_rows.deaths_next[hit][0]:,.0f} |"
            )
    return "\n".join(lines)


def top_k_precision(rows: Rows, predicted: np.ndarray, label: np.ndarray, k: int = 10) -> float:
    hits = total = 0
    for week in np.unique(rows.week):
        here = np.flatnonzero(rows.week == week)
        top = here[np.argsort(-predicted[here], kind="stable")[:k]]
        hits += label[top].sum()
        total += len(top)
    return hits / total if total else float("nan")


def save_weights(model: NegBin, rows: Rows, path: Path = risk.WEIGHTS_FILE) -> dict:
    out = {
        "model": f"negative binomial (NB2, log link) of deaths in the next {HORIZON} weeks",
        "fitted_on": [str(rows.week.min()), str(rows.week.max())],
        "country_weeks": len(rows),
        "intercept": round(model.intercept, 4),
        "alpha": round(model.alpha, 4),
        "coefficients": {p: round(float(b), 4) for p, b in zip(FITTED, model.coef, strict=True)},
        "weights": weights_from(model),
        "note": "Signal is not fitted (too few GDELT weeks) and keeps its hand-set points.",
    }
    path.write_text(json.dumps(out, indent=2) + "\n", newline="\n")
    return out


def load_rows(half_life: float = risk.HALF_LIFE_WEEKS) -> Rows:
    from sqlalchemy import text

    from app.db import session_factory

    with session_factory()() as db:
        weeks, data, provisional_after = risk.load_inputs(db)
        neighbours = risk.neighbours_from_cells(db.execute(text(risk.CELLS_SQL)))
    return build_rows(weeks, data, neighbours, provisional_after, half_life)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.risk_model")
    parser.add_argument("command", choices=["backtest", "fit"])
    parser.add_argument("--first-year", type=int, default=FIRST_TEST_YEAR)
    parser.add_argument("--report", type=Path, help="also write the backtest report here")
    parser.add_argument(
        "--half-life",
        type=float,
        default=risk.HALF_LIFE_WEEKS,
        help="try another History half-life in weeks (backtest only; scoring keeps its own)",
    )
    args = parser.parse_args()
    if args.command == "fit" and args.half_life != risk.HALF_LIFE_WEEKS:
        parser.error("fit uses the scoring half-life; change HALF_LIFE_WEEKS in app.risk instead")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rows = load_rows(args.half_life)
    final = fit_nb(rows.levels, rows.deaths_next)
    if args.command == "fit":
        print(json.dumps(save_weights(final, rows), indent=2))
        print(f"wrote {risk.WEIGHTS_FILE}; run `python -m app.risk build` to rescore")
        return
    text = report(backtest(rows, args.first_year), final, rows)
    print(text)
    if args.report:
        args.report.write_text(text + "\n", newline="\n")


if __name__ == "__main__":
    main()
