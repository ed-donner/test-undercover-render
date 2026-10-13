"""Amounts in US dollars as people read them, such as $1,250.00."""


def dollars(amount: float) -> str:
    """Format an amount like $1,250.00."""
    return f"${amount:,.2f}"
