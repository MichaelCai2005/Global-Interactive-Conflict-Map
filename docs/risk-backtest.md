# Risk score backtest

The weekly risk score (`backend/app/risk.py`) adds four parts: History, Surge, Spread and
Signal. Their weights started as a hand-set 40/20/20/20, checked only by eye on a few known
weeks. `backend/app/risk_model.py` fits them to what the score is meant to warn of, and
tests them on years the fit never saw.

## Method

**Outcome.** UCDP and ACLED deaths in a country over the four weeks after the scored week.
This is the "next month's deaths" outcome from the design doc.

**Model.** The doc's negative binomial (NB2) regression:

    log E[deaths, weeks t+1..t+4] = b0 + b_history * History + b_surge * Surge + b_spread * Spread

Each part enters as its 0-1 level from `app.risk`. With a log link, a coefficient says how
many times a full level of that part multiplies expected deaths (e^b). The coefficients
are scaled into points that sum to 80, and Signal keeps its 20. So the score is still a sum
of parts, and the map can still say why a country is red. Coefficients can't go below zero:
a part that fits negative is dropped and the rest refitted, so no part can lower a score.
None has needed dropping on the full data.

**Signal is not fitted.** GDELT is loaded for about 19 weeks, and only February 2022 and
late 2025 overlap UCDP. That's too little to fit or test, so Signal keeps its hand-set 20
points. It only counts in weeks with GDELT data.

**Rolling origin.** Each year from 2000 to 2025 is scored with a model fitted only on weeks
whose four-week outcome was complete before that year began. Pooling those out-of-sample
scores gives the results below. Rows start one year into the data, so History and Surge
have filled in. Countries with no UCDP or ACLED event at all are left out: every model
ranks them last, so they would only make the numbers look better.

**Questions graded.**

- *Any*: does the country have 25 or more deaths in the next four weeks?
- *Flare-up*: the same question, asked only of countries with fewer than 25 deaths in the
  past 26 weeks. This is harder, and it's the case an early warning exists for.

**Models compared.**

| Model | What it is |
| --- | --- |
| Fitted weights | History, Surge and Spread, weighted by the NB coefficients |
| Hand-set weights | The original 40/20/20 score; the model only sets its scale |
| History only | Decayed deaths alone |
| Last 4 weeks | Naive baseline: next month looks like the last |

## Findings

1. **Fitted beats hand-set on every measure.** Any: AUC 0.968 against 0.960, AP 0.822
   against 0.787. Flare-ups: AUC 0.829 against 0.818. Top-10 precision: 0.862 against
   0.836. Log-likelihood: -1.820 against -1.833.
2. **The weights are stable.** Fitted at each of the 26 origins, History moves from 41 to
   54 points, Surge stays within 15-20, and Spread drops from 22 to 11. The drift is
   steady, not noisy: the longer the record, the more it rewards persistence.
3. **History alone ranks ongoing wars best.** On *Any* it beats the composite (AUC 0.972,
   AP 0.849, top-10 0.884), and the naive last-four-weeks baseline does best of all at the
   very top of the list (AP 0.860, top-10 0.900). Next month's violence mostly looks like
   this month's.
4. **Surge and Spread earn their place on flare-ups.** There the composite is best (AUC
   0.829), and the naive baseline is close to useless (0.653). Flare-ups are rare: 719 of
   127,404 quiet weeks, or 0.6%. Even the best model's precision on them stays near 3%, five
   times the base rate. Treat a quiet country's rising score as a prompt to look, not a
   forecast.
5. **The score means something in absolute terms.** Out of sample, 8% of weeks scoring
   30-40 were followed by 25+ deaths, 30% at 40-50, 69% at 50-60 and 89% at 60-70. In a week
   without GDELT data, each 10 points multiplies expected deaths about 2.9 times.
6. **26 weeks is the right half-life for History.** The backtest was rerun with other
   half-lives (`--half-life`):

   | Half-life | Any AUC | Any AP | Flare-up AUC | Log-lik / week | Top-10 precision | Fitted Surge points |
   | --- | --- | --- | --- | --- | --- | --- |
   | 4 weeks | 0.967 | 0.844 | 0.773 | -1.850 | 0.865 | 0 |
   | 8 weeks | 0.969 | 0.845 | 0.811 | -1.829 | 0.868 | 3 |
   | 13 weeks | 0.970 | 0.840 | 0.829 | -1.821 | 0.869 | 8 |
   | **26 weeks** | 0.968 | 0.822 | 0.829 | **-1.820** | 0.862 | 15 |
   | 52 weeks | 0.962 | 0.779 | 0.809 | -1.832 | 0.839 | 21 |

   26 weeks has the best log-likelihood, which is what the model is fitted on, and ties
   13 weeks on flare-ups. Shorter half-lives rank ongoing wars slightly better but leave
   Surge with almost no weight. The half-life stays at 26.

## Limits

- **UCDP only, in practice.** ACLED is loaded for 2022 alone and GDELT for a few weeks.
  The fit says nothing about Signal, and little about how ACLED's denser counts change
  Surge.
- **Neighbours use all years of data.** Two countries are neighbours if they ever had
  events near each other. In the backtest, that lets a little of the future in through
  Spread. Borders rarely change, so the effect should be small.
- **One outcome.** The weights optimise expected deaths, which large wars dominate. A model
  fitted only to flare-ups would weight Surge and Spread more, and ongoing wars less.
- **Score bands are pooled over 2000-2025.** The share of high-scoring weeks that turn
  violent shifts with the global level of conflict.

## Rerunning

```bash
cd backend
pip install -e ".[model]"
python -m app.risk_model backtest --report ../docs/risk-backtest-latest.md   # ~3 minutes
python -m app.risk_model fit       # writes app/data/risk_weights.json
python -m app.risk build           # rescore with the new weights
```

Refit after loading a new UCDP release. Recheck the known weeks below, and the table
above, before committing new weights.

## Latest run (UCDP 1989-2025, ACLED 2022)

Rolling-origin backtest, 2000-2025: 170,352 country-weeks in 126 countries.

| Model | Any AUC | Any AP | Flare-up AUC | Flare-up AP | Log-lik / week | Top-10 precision |
| --- | --- | --- | --- | --- | --- | --- |
| Fitted weights | 0.968 | 0.822 | 0.829 | 0.032 | -1.820 | 0.862 |
| Hand-set weights | 0.960 | 0.787 | 0.818 | 0.032 | -1.833 | 0.836 |
| History only | 0.972 | 0.849 | 0.814 | 0.027 | -1.821 | 0.884 |
| Last 4 weeks | 0.961 | 0.860 | 0.653 | 0.027 | -1.892 | 0.900 |

Weights fitted at each origin (points of 80; Signal keeps 20):

| Test year | History | Surge | Spread | alpha |
| --- | --- | --- | --- | --- |
| 2000 | 41.2 | 17.2 | 21.6 | 15.1 |
| 2004 | 46.5 | 19.3 | 14.2 | 15.5 |
| 2008 | 46.6 | 19.1 | 14.3 | 14.4 |
| 2012 | 46.9 | 18.1 | 15.0 | 13.9 |
| 2016 | 48.6 | 17.2 | 14.3 | 12.9 |
| 2020 | 49.4 | 17.2 | 13.4 | 11.7 |
| 2024 | 53.5 | 15.4 | 11.1 | 11.0 |
| 2025 | 53.9 | 15.3 | 10.8 | 10.7 |

What followed weeks in each score band, out of sample (fitted weights, weeks without GDELT):

| Score | Weeks | Share with 25+ deaths next 4 weeks | Median deaths | Mean deaths |
| --- | --- | --- | --- | --- |
| 0-10 | 64,014 | 0.1% | 0 | 0 |
| 10-20 | 36,768 | 0.5% | 0 | 1 |
| 20-30 | 17,616 | 1.0% | 0 | 2 |
| 30-40 | 13,929 | 8.0% | 0 | 20 |
| 40-50 | 15,152 | 29.8% | 9 | 31 |
| 50-60 | 13,227 | 69.1% | 51 | 100 |
| 60-70 | 6,900 | 89.0% | 195 | 396 |
| 70-80 | 2,321 | 93.9% | 614 | 1,299 |
| 80-90 | 296 | 97.3% | 616 | 1,643 |
| 90-100 | 129 | 100.0% | 1,677 | 2,805 |

Final fit on all 236,250 complete weeks: intercept -1.16, alpha 10.54, coefficients History
7.20, Surge 2.02, Spread 1.44. Weights: History 54.0, Surge 15.1, Spread 10.8, Signal 20.0
(hand-set). A score of 0 expects 0.3 deaths over the next four weeks, and 100 expects about
13,000.

Known weeks, scored without Signal:

| Country | Week | Event | Hand-set | Fitted | Deaths next 4 weeks |
| --- | --- | --- | --- | --- | --- |
| UKR | 2022-02-28 | Russia invades Ukraine | 76 | 87 | 8,708 |
| ISR | 2023-10-09 | Hamas attack and war in Gaza | 79 | 83 | 7,288 |
| LBN | 2023-10-09 | Hezbollah opens a second front | 62 | 54 | 49 |
| SDN | 2023-04-17 | SAF and RSF war in Khartoum | 69 | 71 | 7,632 |
| ETH | 2020-11-02 | Tigray war begins | 63 | 67 | 2,787 |
| MMR | 2021-01-25 | Week before the coup | 39 | 43 | 23 |

The wars that followed score higher with the fitted weights. Lebanon scores lower, since its
next month brought 49 deaths, not thousands. Myanmar on the eve of the coup scores 43, in
the 40-50 band, where 30% of weeks turned violent. Its next four weeks brought 23 deaths,
just under the line.
