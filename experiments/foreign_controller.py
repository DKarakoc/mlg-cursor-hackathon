"""Contest controller for Traffic Lights Arena."""

MEMORY = {"shape": None, "items": {}}

PARAMS = {
    "Q_WEIGHT": 1.0,
    "AGE_WEIGHT": 0.06,
    "STARVE_WEIGHT": 0.10,
    "BLOCK_WEIGHT": 1.6,
    "DOWNSTREAM_QUEUE_WEIGHT": 0.35,
    "SWITCH_MARGIN": 2.6,
    "MIN_EXTRA_HOLD": 2,
    "MAX_STARVE": 40,
    "ENDGAME_START": 150,
    "ENDGAME_EXIT_WEIGHT": 2.4,
    "ENDGAME_INTERNAL_PENALTY": 0.7,
    "ALIGN_WEIGHT": 0.20,
}

DIRECTIONS = ("N", "S", "E", "W")
AXIS_DIRECTIONS = {
    "NS_GREEN": ("N", "S"),
    "EW_GREEN": ("E", "W"),
}


def _axis(direction):
    return "NS_GREEN" if direction in ("N", "S") else "EW_GREEN"


def _row_col(intersection_id):
    return ord(intersection_id[0]) - 65, int(intersection_id[1:]) - 1


def _intersection_id(row, col):
    return f"{chr(65 + row)}{col + 1}"


def _next_intersection(item, direction, rows, cols):
    row, col = _row_col(item)
    if direction == "N":
        row -= 1
    elif direction == "S":
        row += 1
    elif direction == "E":
        col += 1
    else:
        col -= 1
    if row < 0 or row >= rows or col < 0 or col >= cols:
        return None
    return _intersection_id(row, col)


def _reset_if_needed(state):
    shape = (state["map"]["rows"], state["map"]["cols"])
    if state["tick"] == 0 or MEMORY.get("shape") != shape:
        MEMORY["shape"] = shape
        MEMORY["items"] = {
            item: {
                "last_requested": data["phase"]
                if data["phase"] in ("NS_GREEN", "EW_GREEN")
                else "NS_GREEN",
                "starved_ns": 0,
                "starved_ew": 0,
            }
            for item, data in state["intersections"].items()
        }


def _memory_for(item, phase):
    memory = MEMORY["items"].setdefault(
        item,
        {"last_requested": phase, "starved_ns": 0, "starved_ew": 0},
    )
    if memory["last_requested"] not in ("NS_GREEN", "EW_GREEN"):
        memory["last_requested"] = "NS_GREEN"
    return memory


def _link_fill(state, item, target):
    link = state["links"].get(f"{item}->{target}")
    if not link:
        return 0.0
    return link["vehicles"] / max(1, link["capacity"])


def _downstream_blockage(state, item, direction, rows, cols):
    target = _next_intersection(item, direction, rows, cols)
    if target is None:
        return 0.0
    target_state = state["intersections"][target]
    same_direction_queue = target_state["queues"][direction]
    cross_dirs = ("E", "W") if direction in ("N", "S") else ("N", "S")
    cross_queue = target_state["queues"][cross_dirs[0]] + target_state["queues"][cross_dirs[1]]
    return (
        6.0 * _link_fill(state, item, target)
        + PARAMS["DOWNSTREAM_QUEUE_WEIGHT"] * same_direction_queue
        + 0.08 * cross_queue
    )


def _exit_bonus(item, direction, rows, cols, remaining):
    target = _next_intersection(item, direction, rows, cols)
    if remaining > PARAMS["ENDGAME_START"]:
        return 0.0
    if target is None:
        return PARAMS["ENDGAME_EXIT_WEIGHT"] * (1 + (PARAMS["ENDGAME_START"] - remaining) / 60)
    return -PARAMS["ENDGAME_INTERNAL_PENALTY"] * (1 + (PARAMS["ENDGAME_START"] - remaining) / 80)


def _alignment_bonus(state, item, phase, rows, cols):
    row, col = _row_col(item)
    neighbors = []
    if phase == "EW_GREEN":
        if col > 0:
            neighbors.append(_intersection_id(row, col - 1))
        if col + 1 < cols:
            neighbors.append(_intersection_id(row, col + 1))
    else:
        if row > 0:
            neighbors.append(_intersection_id(row - 1, col))
        if row + 1 < rows:
            neighbors.append(_intersection_id(row + 1, col))
    bonus = 0.0
    for neighbor in neighbors:
        data = state["intersections"].get(neighbor)
        if data and data["phase"] == phase:
            bonus += PARAMS["ALIGN_WEIGHT"]
    return bonus


def _update_starvation(memory, data, active_phase):
    ns_waiting = data["queues"]["N"] + data["queues"]["S"] > 0
    ew_waiting = data["queues"]["E"] + data["queues"]["W"] > 0
    if ns_waiting and active_phase != "NS_GREEN":
        memory["starved_ns"] = min(PARAMS["MAX_STARVE"], memory["starved_ns"] + 1)
    else:
        memory["starved_ns"] = max(0, memory["starved_ns"] - 2)
    if ew_waiting and active_phase != "EW_GREEN":
        memory["starved_ew"] = min(PARAMS["MAX_STARVE"], memory["starved_ew"] + 1)
    else:
        memory["starved_ew"] = max(0, memory["starved_ew"] - 2)


def _phase_score(state, item, phase, memory):
    rows = state["map"]["rows"]
    cols = state["map"]["cols"]
    remaining = state["remaining_ticks"]
    data = state["intersections"][item]
    score = 0.0
    for direction in AXIS_DIRECTIONS[phase]:
        queue = data["queues"][direction]
        oldest = data["oldest_wait"][direction]
        score += queue * PARAMS["Q_WEIGHT"]
        score += oldest * PARAMS["AGE_WEIGHT"]
        score += _exit_bonus(item, direction, rows, cols, remaining) * queue
        score -= PARAMS["BLOCK_WEIGHT"] * _downstream_blockage(state, item, direction, rows, cols)
    if phase == "NS_GREEN":
        score += memory["starved_ns"] * PARAMS["STARVE_WEIGHT"]
    else:
        score += memory["starved_ew"] * PARAMS["STARVE_WEIGHT"]
    score += _alignment_bonus(state, item, phase, rows, cols)
    return score


def _choose_phase(state, item):
    data = state["intersections"][item]
    phase = data["phase"]
    memory = _memory_for(item, phase if phase in ("NS_GREEN", "EW_GREEN") else "NS_GREEN")
    active_phase = phase if phase in ("NS_GREEN", "EW_GREEN") else memory["last_requested"]
    _update_starvation(memory, data, active_phase)

    ns_score = _phase_score(state, item, "NS_GREEN", memory)
    ew_score = _phase_score(state, item, "EW_GREEN", memory)
    raw_best = "NS_GREEN" if ns_score >= ew_score else "EW_GREEN"

    if phase not in ("NS_GREEN", "EW_GREEN"):
        memory["last_requested"] = raw_best
        return raw_best

    if raw_best == phase:
        memory["last_requested"] = phase
        return phase

    extra_green_age = max(0, data["phase_age"] - 5)
    hold_bonus = max(0, PARAMS["MIN_EXTRA_HOLD"] - extra_green_age) * 1.5
    margin = PARAMS["SWITCH_MARGIN"] + hold_bonus
    if data["can_switch"]:
        if raw_best == "NS_GREEN" and ns_score > ew_score + margin:
            memory["last_requested"] = "NS_GREEN"
            return "NS_GREEN"
        if raw_best == "EW_GREEN" and ew_score > ns_score + margin:
            memory["last_requested"] = "EW_GREEN"
            return "EW_GREEN"

    memory["last_requested"] = phase
    return phase


def control(state):
    """Return requested green phases for every intersection."""
    _reset_if_needed(state)
    return {item: _choose_phase(state, item) for item in state["intersections"]}
