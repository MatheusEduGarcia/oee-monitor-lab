import pytest

from oeelab.contract import validate
from oeelab.weeklab import lines, run_week

KPIS = ("TEEP", "OAE", "OOE", "OEE")


@pytest.fixture(scope="module")
def week():
    return run_week()


def test_every_second_of_the_week_is_accounted_for(week):
    measured, truth, c = week
    assert c.rows("SELECT COUNT(*) n FROM dlq")[0]["n"] == 0
    for t in measured.values():
        assert abs(sum(t.seconds.values()) - 7 * 24 * 3600) < 1


def test_indicators_match_the_truth_of_the_script(week):
    measured, truth, _ = week
    for name, m in measured.items():
        t = truth[name]
        assert (m.good, m.defect) == (t.good, t.defect)
        for k in KPIS:
            assert m.indicator(k) == pytest.approx(t.indicator(k), abs=1e-6), (name, k)
        assert len(m.failures) == len(t.failures)
        assert m.mtbf_h == pytest.approx(t.mtbf_h, rel=1e-6)
        assert m.mttr_min == pytest.approx(t.mttr_min, rel=1e-6)
    assert lines(measured) == pytest.approx(lines(truth))


def test_the_family_is_ordered_by_its_reference_time(week):
    measured, _, _ = week
    for m in measured.values():
        assert m.indicator("TEEP") < m.indicator("OAE") < m.indicator("OOE") < m.indicator("OEE") < 1
        assert m.indicator("OEE") == pytest.approx(m.availability * m.performance * m.quality)


def test_stop_reasons_are_part_of_the_contract():
    base = {"v": 1, "seq": 1, "boot": "a1b2c3", "value": 0, "running": False}
    assert validate("state", {**base, "category": "failure", "reason": "seal-wear"}) == []
    assert validate("state", {**base, "category": "broken"})                      # unknown category
    assert validate("state", {**base, "reason": "Seal Wear"})                      # not a slug
    assert validate("state", {**base, "value": 1, "running": True, "category": "planned"})   # running has no reason
