"""Compartment state machine (pure functions, no I/O). See api-contract.md, 'Compartment states'."""

# keypad code accepted: (current state, code purpose) -> new state
_ON_CODE = {
    ("deposit_reserved", "deposit"): "deposit_open",
    ("pickup_reserved", "pickup"): "pickup_open",
}

# '#' pressed and IR read: (current state, occupied) -> (new state, event)
_ON_REPORT = {
    ("deposit_open", True): ("occupied", "deposited"),
    ("deposit_open", False): ("free", "deposit_cancelled"),
    ("pickup_open", False): ("free", "picked_up"),
    ("pickup_open", True): ("occupied", "pickup_incomplete"),
}

# LCD texts (max 16 characters)
MESSAGES = {
    "deposited": "Item stored",
    "deposit_cancelled": "Deposit cancel",
    "picked_up": "Thank you!",
    "pickup_incomplete": "Item still in",
}


def next_state_on_code(state: str, purpose: str) -> str | None:
    return _ON_CODE.get((state, purpose))


def next_state_on_report(state: str, occupied: bool) -> tuple[str, str] | None:
    return _ON_REPORT.get((state, occupied))
