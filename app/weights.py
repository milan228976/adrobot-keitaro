class InvalidShares(ValueError):
    """Pinned shares cannot form a valid split."""


def distribute(pins: dict[int, int | None]) -> dict[int, int]:
    """Split 100% evenly among unpinned offers, in display order."""
    if not pins:
        return {}

    fixed = [share for share in pins.values() if share is not None]
    remaining = 100 - sum(fixed)
    free_count = len(pins) - len(fixed)
    if remaining < 0 or any(not 0 <= share <= 100 for share in fixed):
        raise InvalidShares("Закреплённые доли должны быть от 0 до 100%, в сумме до 100%.")
    if not free_count and remaining:
        raise InvalidShares("Закреплённые доли должны составлять 100%. Освободите одну долю.")

    even, remainder = divmod(remaining, free_count) if free_count else (0, 0)
    result = {}
    for offer_id, pin in pins.items():
        if pin is None:
            result[offer_id] = even + int(remainder > 0)
            remainder -= 1
        else:
            result[offer_id] = pin
    return result
