"""Generate PaymentEventLog rows for one account over its contract age.

Reads HealthProfile.payment_state and payment_state_change_day from
archetypes.py. Produces invoice-cycle payment events matching AGT-803 spec.

Most archetypes have payment_state="current" — those generate one
clean payment event per billing cycle (monthly). Archetypes with a
payment_state_change_day generate state-transition events at that point,
following the AGT-803 retry-and-escalation chain (Retry 1 → Retry 2 →
Retry 3 → Failed) when transitioning into overdue/failed.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional
import uuid

from archetypes import HealthProfile


def _emit(account_id: str, invoice_id: str, event_type: str,
          new_state: str, prior_state: Optional[str],
          event_at: datetime, reason: str) -> dict:
    return {
        "payment_event_id": str(uuid.uuid4()),
        "account_id": account_id,
        "invoice_id": invoice_id,
        "event_type": event_type,
        "prior_state": prior_state,
        "new_state": new_state,
        "transition_reason": reason,
        "event_at": event_at.isoformat() + "Z",
    }


def generate_payment_events(
    account_id: str,
    contract_start: datetime,
    contract_age_days: int,
    profile: HealthProfile,
    rng: random.Random,
    billing_cadence_days: int = 30,
) -> list[dict]:
    """Generate PaymentEventLog rows for one account over its contract age."""
    rows: list[dict] = []
    state = "current"
    change_day = profile.payment_state_change_day
    target_state = profile.payment_state

    cycle = 0
    while True:
        cycle_day = cycle * billing_cadence_days
        if cycle_day >= contract_age_days:
            break

        invoice_id = f"inv_{account_id}_{cycle:03d}"
        due_date = contract_start + timedelta(days=cycle_day)

        # Most cycles: clean payment success
        if change_day is None or cycle_day < change_day or target_state == "current":
            rows.append(_emit(
                account_id, invoice_id,
                event_type="payment_success",
                new_state="current",
                prior_state=state,
                event_at=due_date,
                reason="invoice_paid_on_time",
            ))
            state = "current"
            cycle += 1
            continue

        # On the cycle that crosses change_day: emit transition chain
        if target_state in ("overdue", "failed", "suspended"):
            # Retry 1
            rows.append(_emit(
                account_id, invoice_id, "retry_1_failure",
                new_state="overdue", prior_state=state,
                event_at=due_date + timedelta(minutes=15),
                reason="card_declined",
            ))
            state = "overdue"

            if target_state in ("failed", "suspended"):
                # Retry 2 → 3 → Failed
                rows.append(_emit(
                    account_id, invoice_id, "retry_2_failure",
                    new_state="overdue", prior_state="overdue",
                    event_at=due_date + timedelta(days=1),
                    reason="card_declined",
                ))
                rows.append(_emit(
                    account_id, invoice_id, "retry_3_failure",
                    new_state="failed", prior_state="overdue",
                    event_at=due_date + timedelta(days=2),
                    reason="all_retries_exhausted",
                ))
                state = "failed"

            if target_state == "suspended":
                rows.append(_emit(
                    account_id, invoice_id, "manual_suspension",
                    new_state="suspended", prior_state="failed",
                    event_at=due_date + timedelta(days=5),
                    reason="finance_director_initiated",
                ))
                state = "suspended"

        cycle += 1

    return rows
