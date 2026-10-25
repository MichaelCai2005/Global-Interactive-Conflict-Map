import io

from sqlalchemy import select, update

from app.conflict_type import classify_acled, classify_gdelt, reclassify
from app.ingest import acled, gdelt, ucdp
from app.models import Event
from tests.builders import acled_csv, acled_row, gdelt_row, gdelt_tsv, ucdp_csv, ucdp_row
from tests.test_ingest import load_sample


def test_gdelt_sides_decide_the_kind():
    # A state against a state or an armed group.
    assert classify_gdelt("190", "RUS", "UKR") == "state_based"
    assert classify_gdelt("193", "NGAMIL", "NGAREB") == "state_based"
    assert classify_gdelt("190", "COP", "UAF") == "state_based"
    # Armed groups against each other.
    assert classify_gdelt("190", "PSEREB", "PSEUAF") == "non_state"
    assert classify_gdelt("190", "RAD", "UAF") == "non_state"
    # Someone armed, or unnamed, attacking unarmed people.
    assert classify_gdelt("190", "UAF", "CVL") == "one_sided"
    assert classify_gdelt("1823", "SDNMIL", "SDNEDU") == "one_sided"
    assert classify_gdelt("190", None, "CVL") == "one_sided"


def test_gdelt_sides_that_do_not_settle_it_are_unclear():
    # Unarmed people as the side that acts.
    assert classify_gdelt("190", "EDU", "USA") is None
    assert classify_gdelt("190", "CVL", "CVL") is None
    # An armed group with no named target.
    assert classify_gdelt("193", "UAF", None) is None
    # Regions and blocs are not states.
    assert classify_gdelt("190", "EUR", "AFR") is None
    # A country's own police against "the country" is not a state at war with itself.
    assert classify_gdelt("190", "USACOP", "USA") is None
    # A country, government or police alone is a news story; a military alone is war.
    assert classify_gdelt("190", "USA", None) is None
    assert classify_gdelt("190", None, "GOV") is None
    assert classify_gdelt("193", "COP", None) is None
    assert classify_gdelt("193", "NGAMIL", None) == "state_based"
    # Criminals are mostly crime, which none of the kinds covers.
    assert classify_gdelt("193", "COP", "CRM") is None
    assert classify_gdelt("190", "CRM", "UAF") is None
    assert classify_gdelt("190", "USA", "CRM") is None


def test_a_country_counts_as_a_state_only_abroad():
    # Russia acting in Ukraine is a state at war; "the US" in a US story is where the news is.
    assert classify_gdelt("190", "RUS", None, "UKR") == "state_based"
    assert classify_gdelt("190", "USA", None, "USA") is None
    # Israel against civilians in Gaza is one-sided; at home, a country against civilians
    # of no named country is unclear.
    assert classify_gdelt("190", "ISR", "CVL", "PSE") == "one_sided"
    assert classify_gdelt("190", "ISR", "CVL", "ISR") is None


def test_gdelt_event_codes_fill_in_what_the_sides_leave_open():
    # Artillery and air strikes are fired by militaries.
    assert classify_gdelt("195", "UAF", None) == "state_based"
    assert classify_gdelt("194", None, None) == "state_based"
    # Mass violence is one-sided unless both sides are fighting forces.
    assert classify_gdelt("202", "UAF", None) == "one_sided"
    assert classify_gdelt("202", "RUS", "UKR") == "state_based"


def test_acled_sides_decide_the_kind():
    assert classify_acled("battle", "State forces", "Rebel group") == "state_based"
    assert classify_acled("battle", "Political militia", "Identity militia") == "non_state"
    assert classify_acled("violence_against_civilians", "Rebel group", "Civilians") == "one_sided"
    assert classify_acled("explosion_remote_violence", "State forces", None) == "state_based"
    assert classify_acled("battle", "2", "3") == "non_state"  # older numbered files
    assert classify_acled("explosion_remote_violence", "Rebel group", None) is None
    # ACLED's own type settles an attack on civilians whose sides are not coded.
    assert classify_acled("violence_against_civilians", None, None) == "one_sided"


def test_parsers_set_the_kind():
    [u] = ucdp.parse(io.StringIO(ucdp_csv([ucdp_row(type_of_violence="2")])))
    assert u.event.conflict_type == "non_state"
    battle, protest = acled.parse(
        io.StringIO(
            acled_csv(
                [
                    acled_row(inter1="Rebel group", inter2="Political militia"),
                    acled_row(event_id_cnty="TST101", event_type="Protests", inter2=""),
                ]
            )
        )
    )
    assert battle.event.conflict_type == "non_state"
    assert protest.event.conflict_type is None
    fight, threat = gdelt.parse(
        io.StringIO(
            gdelt_tsv(
                [
                    gdelt_row(Actor1Code="TSTMIL", Actor2Code="TSTCVL"),
                    gdelt_row(GLOBALEVENTID="2", EventRootCode="13", EventCode="130"),
                ]
            )
        )
    )
    assert fight.event.conflict_type == "one_sided"
    assert threat.event.conflict_type is None


def test_reclassify_sorts_stored_events_again(session, tmp_path):
    load_sample(session, tmp_path)
    session.execute(update(Event).values(conflict_type=None))
    session.commit()

    counts = reclassify(session)

    kinds = session.execute(
        select(Event.source, Event.is_violent, Event.conflict_type).order_by(Event.id)
    ).all()
    # The sample's two GDELT fights are Testland's military against rebels, its protest is
    # not violence, and UCDP's own types are not touched.
    assert sorted(kinds) == [
        ("gdelt", False, None),
        ("gdelt", True, "state_based"),
        ("gdelt", True, "state_based"),
        ("ucdp", True, None),
        ("ucdp", True, None),
    ]
    assert counts == {"state_based": 2}
    assert reclassify(session) == counts
