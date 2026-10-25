import numpy as np

from app import headline_model
from app.headline_model import HeadlineModel, evaluate, fit, fit_logistic, training_headlines
from app.ingest.gdelt_screen import NOT_CONFLICT, NOT_VIOLENCE, rescreen, screen_by_model
from app.ingest.loader import ingest_file
from tests.builders import gdelt_row, gdelt_tsv, ucdp_csv, ucdp_row
from tests.test_ingest import write

# A stand-in for the sentence embedding: one dimension per word, so tests need no download.
VOCABULARY = ["attack", "troops", "killed", "rebels", "zoo", "penguins", "debate", "forest"]


def embed(texts):
    vectors = np.array([[float(word in t.split()) for word in VOCABULARY] + [1.0] for t in texts])
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


# Conflict words count for, the others against.
MODEL = HeadlineModel(embed, [4, 4, 2, 4, -4, -4, -4, -4, 0], 0.0)

ATTACK = "https://news.example/rebels-attack-troops-near-testville"
ZOO = "https://news.example/zoo-welcomes-penguins-after-attack-scare"


def test_fit_logistic_separates_the_classes():
    x = embed(["rebels attack", "troops killed", "zoo penguins", "forest debate"])
    coefficients, intercept = fit_logistic(x, np.array([1.0, 1.0, 0.0, 0.0]))
    p = 1 / (1 + np.exp(-(x @ coefficients + intercept)))
    assert (p[:2] > 0.5).all() and (p[2:] < 0.5).all()


def test_probabilities_embed_each_headline_once():
    seen = []

    def counting(texts):
        seen.append(list(texts))
        return embed(texts)

    model = HeadlineModel(counting, MODEL.coefficients, 0.0)
    p = model.conflict_probabilities(["rebels attack", "zoo penguins", "rebels attack"])
    assert p[0] == p[2] > 0.9 > 0.1 > p[1]
    assert seen == [["rebels attack", "zoo penguins"]]


def test_screen_by_model_reads_only_what_the_rules_kept():
    urls = [ATTACK, ZOO, ZOO, "https://news.example/12345", None]
    reasons = [None, None, NOT_VIOLENCE, None, None]
    assert screen_by_model(MODEL, urls, reasons) == [None, NOT_CONFLICT, NOT_VIOLENCE, None, None]
    # Without a model, the rules' reasons stand.
    assert screen_by_model(None, urls, reasons) == reasons


def test_the_model_does_not_overrule_a_word_of_war():
    # The model finds the zoo and the penguins unlike war, but the troops are war.
    zoo_troops = "https://news.example/zoo-penguins-welcome-troops-home"
    assert MODEL.conflict_probabilities(["zoo penguins welcome troops home"])[0] < 0.5
    assert screen_by_model(MODEL, [zoo_troops], [None]) == [None]
    # A protest alone is no word of war.
    zoo_protest = "https://news.example/zoo-penguins-spark-protest"
    assert screen_by_model(MODEL, [zoo_protest], [None]) == [NOT_CONFLICT]


def test_ingest_screens_gdelt_with_the_model(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(headline_model, "shared", lambda: MODEL)
    rows = [
        gdelt_row(GLOBALEVENTID="1", SOURCEURL=ATTACK),
        gdelt_row(GLOBALEVENTID="2", ActionGeo_Lat="10", ActionGeo_Long="10", SOURCEURL=ZOO),
        # A protest is no violence to screen, whatever its headline.
        gdelt_row(GLOBALEVENTID="3", EventRootCode="14", EventCode="141", SOURCEURL=ZOO),
    ]
    ingest_file(session, "gdelt", write(tmp_path, "20220301.export.CSV", gdelt_tsv(rows)))

    items = client.get("/events").json()["items"]
    assert sorted((e["event_type"], e["source_url"]) for e in items) == [
        ("fight", ATTACK),
        ("protest", ZOO),
    ]
    # Rescreening without the model brings the zoo story back; with it, it goes again.
    assert rescreen(session) == {None: 2}
    assert rescreen(session, MODEL) == {None: 1, NOT_CONFLICT: 1}


def test_training_headlines_come_from_ucdp_and_screened_gdelt(session, tmp_path):
    ucdp = ucdp_row(source_headline="2 soldiers killed in Testville clash;12.03.2022")
    ingest_file(session, "ucdp", write(tmp_path, "ged.csv", ucdp_csv([ucdp])))
    forest = "https://news.example/retired-teacher-saves-a-forest-in-testville"
    rows = [
        gdelt_row(GLOBALEVENTID="1", SOURCEURL=forest, AvgTone="1.2"),
        gdelt_row(GLOBALEVENTID="2", ActionGeo_Lat="10", ActionGeo_Long="10", SOURCEURL=ATTACK),
    ]
    ingest_file(session, "gdelt", write(tmp_path, "20220301.export.CSV", gdelt_tsv(rows)))

    # The date part of UCDP's headline is too short to keep; the attack was not screened.
    conflict, other = training_headlines(session, leave_out=set())
    assert conflict == ["soldiers killed in testville clash"]
    assert other == ["retired teacher saves a forest in testville"]
    assert training_headlines(session, leave_out={forest})[1] == []

    weights = fit(conflict, other, embed)
    assert (weights["conflict_headlines"], weights["other_headlines"]) == (1, 1)
    assert len(weights["coefficients"]) == len(VOCABULARY) + 1


def test_evaluate_scores_the_labelled_articles():
    table = evaluate(MODEL)
    # The word rules keep all hand-labelled reports of armed conflict but one: police
    # recruits abducted in Pakistan, which reads as crime.
    assert table["conflict"]["rules"] == "46/47"
    assert set(table) == {"conflict", "war_news", "crime", "not_violence", "unclear"}
