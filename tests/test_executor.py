"""STEP 13.4 test_executor (spec defaults: $47.50 min ticket, 8% of stack)."""
from agents.executor import size_ticket


def defaults(desk):
    for k, v in [("executor.stack_pct", 8), ("executor.min_ticket_usd", 47.5), ("executor.max_pool_pct", 2), ("executor.below_min", "bump")]:
        desk.settings.set(k, v)


def test_bump_and_skip(desk):
    defaults(desk)
    size, raw, cap, why = size_ticket(200, 200, 1_000_000, desk.s)
    assert raw == 16 and size == 47.5 and cap == "bumped"
    desk.settings.set("executor.below_min", "skip")
    size, raw, cap, why = size_ticket(200, 200, 1_000_000, desk.s)
    assert size is None and why == "under $47.50"
    print("\n$200 -> $16 -> bump sends $47.50 · skip skips 'under $47.50'")


def test_paper_start_skip_warning(desk):
    defaults(desk)
    desk.settings.set("desk.paper_start_stack", 200)
    desk.db.kv_set("paper_cash", 200)
    desk.settings.set("executor.below_min", "skip")
    tc = desk.settings.ticket_check()
    assert tc[0] == "skip" and "every coin will be skipped, stack under $593.75" in tc[1]
    desk.settings.set("executor.below_min", "bump")
    assert desk.settings.ticket_check()[1] == "tickets bumped to $47.50 = 23.75% of stack"
    print("\n", tc[1])


def test_pool_cap(desk):
    defaults(desk)
    size, raw, cap, why = size_ticket(1_000_000, 1_000_000, 40_000, desk.s)
    assert size == 800 and cap == "max_pool_pct"


def test_no_free_stack(desk):
    defaults(desk)
    assert size_ticket(200, 40, 1_000_000, desk.s)[3] == "no free stack"


def test_owner_budget_30(desk):
    """Christian's settings: $30 stack, 33.3%, $5 min ticket, bump -> $9.99 tickets, ticket check passes."""
    for k, v in [("desk.paper_start_stack", 30), ("desk.stack", 30), ("executor.stack_pct", 33.3), ("executor.min_ticket_usd", 5), ("executor.below_min", "bump")]:
        desk.settings.set(k, v)
    desk.db.kv_set("paper_cash", 30)
    assert desk.settings.ticket_check() is None
    assert size_ticket(30, 30, 50_000, desk.s)[0] == 9.99
