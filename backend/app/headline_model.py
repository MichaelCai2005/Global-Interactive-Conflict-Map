"""A small model that tells a news headline about armed conflict from the rest.

GDELT codes ordinary crime and stories that are not about violence at all with the same
CAMEO codes as war. app.ingest.gdelt_screen's word rules catch most of them; this model
reads what the rules let through. It runs on the CPU, free, with no account or API key:
a sentence embedding (BAAI/bge-small-en-v1.5, 33M parameters, through fastembed's ONNX
runtime, a 70 MB download cached after the first run) and a logistic regression on top,
whose 385 numbers are fitted here and kept in app/data/headline_model.json.

The training data is already in the database, and no one labels anything by hand:

- armed conflict: the headlines UCDP cites for its events (`source_headline`), which are
  news of the fighting UCDP verified;
- not armed conflict: the headlines of GDELT violence the word rules screened out as crime
  or as not about violence. In the hand-labelled sample below, the rules screened out one
  report of armed conflict in 47, so these are nearly clean negatives.

app/data/gdelt_headline_labels.csv holds 280 GDELT articles labelled by hand from two days
of October 2026 (conflict, crime, not_violence, war_news, unclear), which `evaluate` scores
the rules and the model against. Those articles are left out of the training data.

Small chat models (Qwen2.5 0.5B to 3B) asked to sort the same headlines did far worse: they
called most terrorist attacks crime and kept two thirds of the conflict at best. A zero-shot NLI
model came closer but was ten times slower than this.

  python -m app.headline_model fit        fit on the database, write the weights file
  python -m app.headline_model evaluate   score the rules and the model on the labels

Needs fastembed: pip install -e ".[screen]". Without it, ingest uses the rules alone.
"""

import argparse
import csv
import json
import logging
import random
from collections.abc import Callable, Sequence
from datetime import date
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingest import gdelt_screen

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
WEIGHTS_FILE = Path(__file__).parent / "data" / "headline_model.json"
LABELS_FILE = Path(__file__).parent / "data" / "gdelt_headline_labels.csv"

# Events whose headline scores below this are screened out. Chosen on the labelled sample:
# with the rules, it keeps 45 of the 47 conflict articles (the rules alone keep 46) and shows
# 22 crime or non-violent ones instead of 36. Up to 0.3 keeps as many labelled conflict
# articles, but on a real week (10-18 to 10-24) scores of 0.15 to 0.3 hold real fighting
# whose headline names no weapon: settler attacks on diplomats, Russia's attack on a ship.
THRESHOLD = 0.15

# Headlines per class to fit on, and the L2 penalty of the logistic regression.
TRAINING_SIZE = 40_000
L2 = 1.0

Embed = Callable[[Sequence[str]], "np.ndarray"]


class HeadlineModel:
    def __init__(
        self,
        embed: Embed,
        coefficients: Sequence[float],
        intercept: float,
        threshold: float = THRESHOLD,
    ):
        import numpy as np

        self.embed = embed
        self.coefficients = np.asarray(coefficients, dtype=np.float32)
        self.intercept = intercept
        self.threshold = threshold

    def conflict_probabilities(self, headlines: Sequence[str]) -> list[float]:
        """How likely each headline is to report armed conflict, 0 to 1."""
        import numpy as np

        unique = sorted(set(headlines))
        if not unique:
            return []
        scores = self.embed(unique) @ self.coefficients + self.intercept
        by_headline = dict(zip(unique, (1 / (1 + np.exp(-scores))).tolist(), strict=True))
        return [by_headline[h] for h in headlines]


def fastembed_embedder() -> Embed:
    import numpy as np
    from fastembed import TextEmbedding

    model = TextEmbedding(EMBEDDING_MODEL)

    def embed(texts: Sequence[str]) -> np.ndarray:
        vectors = np.array(list(model.embed(list(texts), batch_size=256)), dtype=np.float32)
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    return embed


@cache
def shared() -> HeadlineModel | None:
    """The model for ingest, loaded once; None to screen with the rules alone, when it is
    turned off (GDELT_HEADLINE_MODEL=false), fastembed is not installed, or it won't load."""
    if not get_settings().gdelt_headline_model:
        return None
    try:
        weights = json.loads(WEIGHTS_FILE.read_text())
        return HeadlineModel(fastembed_embedder(), weights["coefficients"], weights["intercept"])
    except ImportError:
        log.info("fastembed is not installed, so GDELT is screened by the word rules alone")
    except Exception:
        log.exception("the headline model did not load, so GDELT is screened by the rules alone")
    return None


def headline(text_: str) -> str:
    """A headline as the words a URL slug would give, so UCDP's headlines and GDELT's URLs
    read alike: "2 soldiers killed in Mali" -> "soldiers killed in mali"."""
    return " ".join(gdelt_screen.words(text_))


def training_headlines(db: Session, leave_out: set[str]) -> tuple[list[str], list[str]]:
    """Armed-conflict headlines from UCDP and others from GDELT, TRAINING_SIZE of each at
    most, drawn the same way on every run."""
    conflict: set[str] = set()
    for (cited,) in db.execute(
        text(
            "SELECT DISTINCT attributes->>'source_headline' FROM events"
            " WHERE source = 'ucdp' AND attributes->>'source_headline' <> ''"
        )
    ):
        # UCDP joins several sources' headlines with ";". Dates and lists of names drop out
        # as too short or too long.
        for part in cited.split(";"):
            words = headline(part)
            if 4 <= len(words.split()) <= 25:
                conflict.add(words)
    other: set[str] = set()
    for (url,) in db.execute(
        text(
            "SELECT source_url FROM events WHERE source = 'gdelt' AND is_violent"
            " AND screened_out IN (:crime, :not_violence)"
        ),
        {"crime": gdelt_screen.CRIME, "not_violence": gdelt_screen.NOT_VIOLENCE},
    ):
        if url not in leave_out:
            words = " ".join(gdelt_screen.headline_words(url))
            if len(words.split()) >= 4:
                other.add(words)
    draw = random.Random(0)
    return (
        draw.sample(sorted(conflict), min(TRAINING_SIZE, len(conflict))),
        draw.sample(sorted(other), min(TRAINING_SIZE, len(other))),
    )


def fit_logistic(x: "np.ndarray", y: "np.ndarray", l2: float = L2) -> tuple["np.ndarray", float]:
    """L2-penalized logistic regression by Newton's method; the intercept goes unpenalized."""
    import numpy as np

    a = np.hstack([x, np.ones((len(x), 1))]).astype(np.float64)
    penalty = l2 * np.eye(a.shape[1])
    penalty[-1, -1] = 0
    w = np.zeros(a.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-(a @ w)))
        gradient = a.T @ (p - y) + penalty @ w
        hessian = (a * (p * (1 - p))[:, None]).T @ a + penalty
        step = np.linalg.solve(hessian, gradient)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w[:-1], float(w[-1])


def fit(conflict: list[str], other: list[str], embed: Embed) -> dict:
    import numpy as np

    if not conflict or not other:
        raise ValueError("fitting needs UCDP headlines and screened GDELT events in the database")
    log.info("embedding %d conflict and %d other headlines", len(conflict), len(other))
    x = embed(conflict + other)
    y = np.array([1.0] * len(conflict) + [0.0] * len(other))
    coefficients, intercept = fit_logistic(x, y)
    return {
        "model": f"logistic regression on {EMBEDDING_MODEL} sentence embeddings (fastembed)",
        "fitted": date.today().isoformat(),
        "conflict_headlines": len(conflict),
        "other_headlines": len(other),
        "intercept": round(intercept, 6),
        "coefficients": [round(float(c), 6) for c in coefficients],
    }


def read_labels(path: Path = LABELS_FILE) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def evaluate(model: HeadlineModel | None, path: Path = LABELS_FILE) -> dict[str, dict[str, str]]:
    """How many labelled articles of each kind the rules, and the rules with the model,
    keep on the map."""
    rows = read_labels(path)
    by_rules = [
        gdelt_screen.screen(
            r["url"], float(r["tone"]), r["adm1"], (r["actor1_code"], r["actor2_code"])
        )
        for r in rows
    ]
    with_model = gdelt_screen.screen_by_model(model, [r["url"] for r in rows], by_rules)
    table: dict[str, dict[str, str]] = {}
    for label in ("conflict", "war_news", "crime", "not_violence", "unclear"):
        picked = [i for i, r in enumerate(rows) if r["label"] == label]
        table[label] = {
            "rules": f"{sum(by_rules[i] is None for i in picked)}/{len(picked)}",
            "rules + model": f"{sum(with_model[i] is None for i in picked)}/{len(picked)}",
        }
    return table


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.headline_model")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fit", help="fit on the database and write " + WEIGHTS_FILE.name)
    commands.add_parser("evaluate", help="score the rules and the model on the labels")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "fit":
        from app.db import session_factory

        # Read, then let the connection go: embedding takes minutes, longer than a hosted
        # database keeps an idle transaction open.
        with session_factory()() as session:
            conflict, other = training_headlines(session, {r["url"] for r in read_labels()})
        weights = fit(conflict, other, fastembed_embedder())
        WEIGHTS_FILE.write_text(json.dumps(weights, indent=1) + "\n", newline="\n")
        print(f"wrote {WEIGHTS_FILE}; run `python -m app.ingest screen-gdelt` to rescreen")
    else:
        weights = json.loads(WEIGHTS_FILE.read_text())
        model = HeadlineModel(fastembed_embedder(), weights["coefficients"], weights["intercept"])
        print("Kept on the map, of the hand-labelled GDELT articles:")
        for label, counts in evaluate(model).items():
            print(
                f"  {label:13} rules {counts['rules']:>7}   rules + model {counts['rules + model']:>7}"
            )


if __name__ == "__main__":
    main()
