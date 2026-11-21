def pack(items, maxw=8):
    """items: list of (number, ms). Returns (cost_ms, workers)."""
    if not items:
        return 0, []
    items = sorted(items, key=lambda x: -x[1])
    best = None
    for k in range(1, min(maxw, len(items)) + 1):
        loads = [0] * k
        ws = [[] for _ in range(k)]
        for n, ms in items:
            j = loads.index(min(loads))
            loads[j] += ms
            ws[j].append(n)
        cost = max(loads) + 2000 * k
        if best is None or cost < best[0]:
            best = (cost, ws)
    return best
