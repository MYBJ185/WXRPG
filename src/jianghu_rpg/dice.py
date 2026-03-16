from __future__ import annotations

import random

from jianghu_rpg.models import RollOutcome


def roll_d20() -> int:
    return random.randint(1, 20)


def resolve_check(stat: str, dc: int, modifier: int, bonus: int = 0) -> RollOutcome:
    roll = roll_d20()
    total = roll + modifier + bonus
    critical = None
    success = total >= dc
    if roll == 20:
        critical = "critical_success"
        success = True
    elif roll == 1:
        critical = "critical_failure"
        success = False
    return RollOutcome(
        stat=stat,
        dc=dc,
        roll=roll,
        modifier=modifier,
        bonus=bonus,
        total=total,
        success=success,
        critical=critical,
    )
