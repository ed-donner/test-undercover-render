import pytest

from backend.tests.settings_requests import change_settings


def line(description, amount, kind="item", **extra):
    """A line of a payout request: one item, with no nights or hours, unless given."""
    return {
        "description": description,
        "amount": amount,
        "kind": kind,
        "quantity": 1,
        "nights": 0,
        "hours": 0,
    } | extra


def payout(client, claim_id, benefit, lines, paid_by_others=0):
    body = {"benefit": benefit, "lines": lines, "paid_by_others": paid_by_others}
    return client.post(f"/api/claims/{claim_id}/payout", json=body)


def steps(result):
    return [(s["step"], s["amount"]) for s in result["calculation"]]


def test_electronics_over_the_per_item_limit(client):
    result = payout(
        client, "CLM-1007", "baggage", [line("Smartphone", 1099, "electronics")]
    ).json()
    assert result["payout"] == 50.0
    assert steps(result) == [
        ("Smartphone, limited to $150.00", 150.0),
        ("Less the deductible", -100.0),
    ]
    assert result["needs_sign_off"] is False


def test_a_payout_over_the_limit_needs_sign_off(client):
    lines = [line("Emergency room", 3800, "expense")]
    result = payout(client, "CLM-1003", "emergency_medical", lines).json()
    assert (result["payout"], result["needs_sign_off"]) == (3750.0, True)


def test_items_with_what_others_paid(client):
    lines = [
        line("Suitcase", 280),
        line("Wool suit", 420),
        line("Four shirts", 120, quantity=4),
    ]
    result = payout(client, "CLM-1002", "baggage", lines, paid_by_others=100).json()
    assert result["payout"] == 550.0
    assert ("Wool suit, limited to $300.00", 300.0) in steps(result)
    assert ("Four shirts", 120.0) in steps(result)
    assert ("Less what others have paid or refunded", -100.0) in steps(result)


def test_a_trip_delay_has_no_deductible(client):
    lines = [
        line("Hotel", 245, "hotel", nights=1),
        line("Meals", 95, "expense"),
        line("Taxis", 80, "expense"),
    ]
    result = payout(client, "CLM-1001", "trip_delay", lines).json()
    assert result["payout"] == 420.0
    assert "Less the deductible" not in [step for step, _ in steps(result)]


def test_the_per_item_limit_counts_each_item(client):
    lines = [line("Three jackets", 600, quantity=3)]
    result = payout(client, "CLM-1007", "baggage", lines).json()
    assert steps(result)[0] == ("Three jackets, limited to $450.00", 450.0)


def test_electronics_plus_raises_the_limit_for_electronics(client):
    lines = [line("Camera", 1500, "electronics"), line("Speaker", 400)]
    result = payout(client, "CLM-1009", "baggage", lines).json()
    assert steps(result)[:2] == [
        ("Camera, limited to $1,200.00", 1200.0),
        ("Speaker, limited to $300.00", 300.0),
    ]


def test_cash_is_limited_in_all(client):
    lines = [line("Cash in a wallet", 80, "cash"), line("Cash in a bag", 70, "cash")]
    result = payout(client, "CLM-1002", "baggage", lines).json()
    assert steps(result)[0] == ("Cash, up to $100 in all", 100.0)
    assert result["payout"] == 50.0


def test_a_hotel_is_limited_by_rooms_and_nights(client):
    lines = [line("Hotel", 2500, "hotel", nights=2)]
    result = payout(client, "CLM-1015", "trip_delay", lines).json()
    assert steps(result)[0] == ("Hotel, limited to $2,100.00", 2100.0)


def test_meals_without_receipts_per_traveler_per_day(client):
    lines = [line("Meals", 900, "meals_without_receipts", hours=30)]
    result = payout(client, "CLM-1015", "trip_delay", lines).json()
    assert steps(result)[0] == ("Meals, limited to $420.00", 420.0)


def test_the_benefit_maximum(client):
    lines = [line("Hotel", 700, "hotel", nights=2), line("Meals", 300, "expense")]
    result = payout(client, "CLM-1001", "trip_delay", lines).json()
    assert steps(result)[-1] == ("Less the amount over the maximum of $800", -200.0)
    assert result["payout"] == 800.0


@pytest.mark.parametrize("benefit", ["trip_cancellation", "trip_interruption"])
def test_a_cancellation_or_interruption_is_capped_at_the_trip_cost(client, benefit):
    lines = [line("Flights and hotel", 1600, "expense")]
    result = payout(client, "CLM-1019", benefit, lines).json()
    assert steps(result) == [
        ("Flights and hotel", 1600.0),
        ("Less the amount over the maximum of $1,400", -200.0),
    ]
    assert result["payout"] == 1400.0


def test_an_interruption_is_capped_at_the_plan_maximum(client):
    lines = [line("Flights home", 12000, "expense")]
    result = payout(client, "CLM-1015", "trip_interruption", lines).json()
    assert steps(result)[-1] == ("Less the amount over the maximum of $9,600", -2400.0)


def test_nothing_below_zero(client):
    lines = [line("Taxi", 40, "expense")]
    result = payout(client, "CLM-1001", "trip_delay", lines, paid_by_others=60).json()
    assert steps(result)[-1] == ("Nothing is left to pay", 20.0)
    assert result["payout"] == 0.0


def test_sign_off_follows_the_limit_in_settings(client):
    change_settings(client, approval_limit=500.0)
    lines = [
        line("Suitcase", 280),
        line("Wool suit", 420),
        line("Four shirts", 120, quantity=4),
    ]
    result = payout(client, "CLM-1002", "baggage", lines, paid_by_others=100).json()
    assert (result["payout"], result["needs_sign_off"]) == (550.0, True)


def test_nothing_is_recorded(client):
    payout(client, "CLM-1001", "trip_delay", [line("Taxis", 80, "expense")])
    claim = client.get("/api/claims/CLM-1001").json()
    assert (claim["status"], claim["decision"]) == ("waiting", None)


@pytest.mark.parametrize(
    ("benefit", "lines"),
    [
        ("pets", [line("Taxis", 80, "expense")]),
        ("baggage", [line("Hat", 30, "souvenir")]),
        ("baggage", [line("Hat", 30, quantity=0)]),
        ("baggage", [{"description": "Hat", "amount": 30, "kind": "item"}]),
        ("baggage", [line("Hat", -30)]),
        ("baggage", [line("", 30)]),
        ("trip_delay", [line("Hotel", 300, "hotel", nights=-1)]),
        ("trip_delay", [line("Meals", 70, "meals_without_receipts", hours=-5)]),
    ],
)
def test_invalid_payout_requests(client, benefit, lines):
    assert payout(client, "CLM-1002", benefit, lines).status_code == 422


def test_what_others_paid_cant_be_negative(client):
    lines = [line("Hat", 30)]
    response = payout(client, "CLM-1002", "baggage", lines, paid_by_others=-10)
    assert response.status_code == 422


def test_an_unknown_claim(client):
    response = payout(client, "CLM-9999", "baggage", [line("Hat", 30)])
    assert response.status_code == 404
