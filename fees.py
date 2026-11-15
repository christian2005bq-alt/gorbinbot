"""FOMO fee model on Solana for PAPER PnL (v2 STEP 13). Gas = 0 (FOMO pays it).
Each side: under $5 -> $0.10 · $5 to $47.50 -> 2% · $47.50 to $190 -> $0.95 · above $190 -> fee_pct."""


def side_fee(ticket_usd: float, ref_discount: float = 0.0, fee_pct: float = 0.45) -> float:
    t = abs(float(ticket_usd))
    if t <= 0:
        return 0.0
    if t < 5:
        fee = 0.10
    elif t <= 47.50:
        fee = 0.02 * t
    elif t <= 190:
        fee = 0.95
    else:
        fee = fee_pct / 100 * t
    return round(fee * (1 - ref_discount), 4)


def round_trip(entry_usd: float, exit_usd: float, ref_discount: float = 0.0, fee_pct: float = 0.45) -> float:
    return round(side_fee(entry_usd, ref_discount, fee_pct) + side_fee(exit_usd, ref_discount, fee_pct), 4)
