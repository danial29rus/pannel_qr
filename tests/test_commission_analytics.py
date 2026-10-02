from decimal import Decimal

from app.services.routing_analytics import commission_margin, percent_of


def test_mulen_commission_margin_is_six_percent_of_payment():
    amount = Decimal("1000")

    assert percent_of(amount, Decimal("13")) == Decimal("130")
    assert percent_of(amount, Decimal("7")) == Decimal("70")
    assert commission_margin(amount, Decimal("13"), Decimal("7")) == Decimal("60")
