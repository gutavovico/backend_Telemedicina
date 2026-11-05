"""Monthly billing arithmetic, independent of the gateway and database."""
from calendar import monthrange
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def next_month(value: datetime, anchor_day: int | None = None):
    value = utc(value)
    if anchor_day:
        anniversary = value.replace(day=min(anchor_day, monthrange(value.year, value.month)[1]))
        if anniversary > value:
            return anniversary  # Keep an already-agreed legacy closing, then rejoin its anchor.
    month = value.month % 12 + 1
    year = value.year + (value.month == 12)
    return value.replace(year=year, month=month,
                         day=min(anchor_day or value.day, monthrange(year, month)[1]))


def adjustment(old_price, new_price, start, end, now):
    start, end, now = map(utc, (start, end, now))
    if not start <= now < end:
        raise ValueError('El ciclo mensual no está vigente')
    def seconds(delta):
        return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1000000)
    remaining = seconds(end - now)
    total = seconds(end - start)
    return (max(Decimal('0'), Decimal(new_price) - Decimal(old_price)) * remaining / total).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)
