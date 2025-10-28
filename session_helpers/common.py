"""Common helper utilities shared by game session modules."""

from decimal import Decimal


def _to_dec(x):
    """Safely coerce values to Decimal with fallback for None."""
    return x if isinstance(x, Decimal) else Decimal(str(x if x is not None else 0))


def _icon_title(title: str) -> None:
    """Render a decorative menu title using box drawing characters."""
    bar = "═" * (len(title) + 2)
    print(f"\n╔{bar}╗")
    print(f"║ {title} ║")
    print(f"╚{bar}╝")
