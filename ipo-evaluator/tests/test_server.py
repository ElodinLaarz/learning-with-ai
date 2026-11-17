"""The web app must run the same engine as the backtest and treat blanks as missing."""
import json

import pytest

from ipo_app import server as S
from ipo_app.engine import recommend as R


@pytest.fixture
def rules_dir(tmp_path, monkeypatch):
    spec = {"name": "return_vs_offer", "coef": -3.0, "mean": 0.0, "std": 1.0, "lo": -9, "hi": 9, "impute": 0.0, "coef_missing": 0.0}
    model = {"intercept": 0.5, "features": [spec], "thresholds": {"buy": 0.55, "avoid": 0.22}}
    r = {"version": "vT", "gates": dict(R.DEFAULT_GATES), "frozen": True,
         "models": {"A_retail": model, "A_offer": model, "B_post_report": model}}
    r["hash"] = R.canonical_hash(r)
    (tmp_path / "vT.json").write_text(json.dumps(r))
    monkeypatch.setattr(R, "RULES_DIR", tmp_path)
    return tmp_path


BODY = {"rule_version": "vT", "name": "X", "exchange": "NYSE", "sic": "7372", "stage": "at_ipo", "access": "retail",
        "offer_price": "20", "price": "21", "shares_offered": "10000000", "shares_outstanding_post": "50000000",
        "revenue": "", "cash": "", "going_concern": "", "overallotment_exercised": "false"}


def test_blank_fields_are_missing_not_zero(rules_dir):
    inp = S.parse_input(BODY)
    assert inp.revenue is None and inp.cash is None and inp.going_concern is None
    assert inp.sic == 7372 and inp.offer_price == 20.0 and inp.overallotment_exercised is False
    assert S.parse_input({**BODY, "going_concern": "true"}).going_concern is True


def test_evaluate_matches_the_engine_and_reports_validation_status(rules_dir):
    res = S.evaluate_request(BODY)
    direct = R.evaluate(S.parse_input(BODY), R.load_rules("vT"))
    assert res["recommendation"] == direct["recommendation"] == R.BUY
    assert res["probability"] == pytest.approx(direct["probability"])
    assert res["rule_hash"] == direct["rule_hash"] and res["rules_frozen"] is True
    assert "label" in res["validation_status"]
    recs = [l["recommendation"] for l in res["price_ladder"]]
    assert R.BUY in recs and R.AVOID in recs          # the ladder shows the recommendation flipping with price
    assert 21 <= res["max_buy_price"] < 21 * 1.1


def test_dilutive_rows_and_missing_criticals(rules_dir):
    body = {**BODY, "dilutive": [{"count": "5000000", "strike": "10", "kind": "option"}, {"count": "", "strike": ""}]}
    res = S.evaluate_request(body)
    assert res["metrics"]["fully_diluted_shares"] == pytest.approx(50e6 + 5e6 * (1 - 10 / 21))
    assert S.evaluate_request({**BODY, "shares_outstanding_post": ""})["recommendation"] == R.ABSTAIN
    assert S.evaluate_request({**BODY, "going_concern": "true"})["recommendation"] == R.AVOID
