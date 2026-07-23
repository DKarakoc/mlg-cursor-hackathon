"""Contest controller for Traffic Lights Arena."""

MEMORY = {
    "shape": None,
    "ns_pressure": 0.0,
    "ew_pressure": 0.0,
}


def _reset_if_needed(state):
    shape = (state["map"]["rows"], state["map"]["cols"])
    if state["tick"] == 0 or MEMORY["shape"] != shape:
        MEMORY["shape"] = shape
        MEMORY["ns_pressure"] = 0.0
        MEMORY["ew_pressure"] = 0.0


def _aggregate_axis_pressure(state):
    ns = 0.0
    ew = 0.0
    for data in state["intersections"].values():
        queues = data["queues"]
        oldest = data["oldest_wait"]
        ns += queues["N"] + queues["S"]
        ew += queues["E"] + queues["W"]
        ns += 0.04 * (oldest["N"] + oldest["S"])
        ew += 0.04 * (oldest["E"] + oldest["W"])
    return ns, ew


def _update_pressure_memory(state):
    ns, ew = _aggregate_axis_pressure(state)
    if state["tick"] < 20:
        alpha = 0.35
    else:
        alpha = 0.08
    MEMORY["ns_pressure"] = (1 - alpha) * MEMORY["ns_pressure"] + alpha * ns
    MEMORY["ew_pressure"] = (1 - alpha) * MEMORY["ew_pressure"] + alpha * ew


def _cycle_for(state):
    rows = state["map"]["rows"]
    cols = state["map"]["cols"]
    cells = rows * cols
    queued = 0
    for data in state["intersections"].values():
        queued += sum(data["queues"].values())

    if cells <= 4:
        return 24 if queued < 55 else 30
    if cells <= 6:
        return 36 if queued < 95 else 40
    return 44 if queued < 170 else 48


def _ns_fraction_for(state):
    rows = state["map"]["rows"]
    cols = state["map"]["cols"]
    cells = rows * cols
    ns = MEMORY["ns_pressure"]
    ew = MEMORY["ew_pressure"]
    total = ns + ew
    if total <= 0.01:
        observed = 0.5
    else:
        observed = ns / total

    if cells <= 4:
        base = 0.50
        low, high = 0.42, 0.60
    elif cells <= 6:
        base = 0.56
        low, high = 0.45, 0.68
    else:
        base = 0.54
        low, high = 0.45, 0.62

    # Keep the split mostly synchronized and stable, but let strong demand move it.
    fraction = 0.55 * base + 0.45 * observed
    if state["remaining_ticks"] < 120:
        fraction = 0.65 * fraction + 0.35 * observed
    return max(low, min(high, fraction))


def control(state):
    """Return requested green phases for every intersection."""
    _reset_if_needed(state)
    _update_pressure_memory(state)
    cycle = _cycle_for(state)
    ns_ticks = round(cycle * _ns_fraction_for(state))
    ns_ticks = max(5, min(cycle - 5, ns_ticks))
    phase = "NS_GREEN" if state["tick"] % cycle < ns_ticks else "EW_GREEN"
    return {item: phase for item in state["intersections"]}
