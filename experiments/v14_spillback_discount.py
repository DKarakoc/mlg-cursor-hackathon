"""Two-regime adaptive traffic controller (mode chosen by smoothed congestion).

LIGHT (queues low): per-intersection actuated max-pressure — skip empty
    greens, switch on local pressure with hysteresis. Desync is harmless
    because links never fill up.
HEAVY (queues high): one synchronized network-wide phase from aggregate
    pressures, minimum phase length grows with congestion. Measured result:
    every desynchronizing variant gridlocks dense grids via link spillback.
Mode uses an EMA with hysteresis and a minimum dwell so it cannot flap.
ENDGAME: queued vehicles that can still exit get a weight bonus (a stranded
    vehicle costs 300; a wait tick costs 1).
"""

# Mode selection (EMA of queued vehicles per intersection)
MODE_ALPHA_UP = 0.08    # congestion is bad news: react fast
MODE_ALPHA_DOWN = 0.02  # ... and require sustained calm to relax
HEAVY_ENTER = 7.0
HEAVY_EXIT = 3.5
MODE_DWELL = 120        # minimum ticks in heavy mode before dropping back
MODE_FREEZE = 150       # no mode changes when this little time remains
# Heavy mode (global rhythm)
H_GAIN = 1.2
H_MARGIN = 5.0
MIN_PHASE_BASE = 12.0
MIN_PHASE_SLOPE = 2.2
MIN_PHASE_CAP = 30.0
SHARE_SCALE = 2.0       # hold time scales by serving axis's demand share x this
SHARE_FLOOR = 8.0       # but never below this many ticks
SHARE_ALPHA = 0.06      # slow EMA so the share tracks demand, not the service cycle
H_STARVE = 90
H_BLOCK_DISCOUNT = 0.3  # discount heavy-mode weight of spillback-blocked movements
# Light mode (per intersection)
L_GAIN = 1.6
L_MARGIN = 2.0
L_DOWNSTREAM = 0.4
L_BLOCK = 11
L_STARVE = 80
# Shared
INCOMING_GREEN = 0.5
INCOMING_RED = 0.25
H_ENDGAME_TICKS = 140
H_SAVABLE_WEIGHT = 25.0
L_ENDGAME_TICKS = 130
L_SAVABLE_WEIGHT = 25.0

DELTA = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
AXIS_DIRECTIONS = {"NS_GREEN": ("N", "S"), "EW_GREEN": ("E", "W")}

_memory = {
    "tick": -1, "phase": "NS_GREEN", "since": 0, "ema": 0.0, "heavy": False,
    "mode_age": 0, "axis_ema": {"NS_GREEN": 1.0, "EW_GREEN": 1.0},
}


def control(state):
    tick = state["tick"]
    if tick <= _memory["tick"]:
        _memory.update(
            phase="NS_GREEN", since=0, ema=0.0, heavy=False, mode_age=0,
            axis_ema={"NS_GREEN": 1.0, "EW_GREEN": 1.0},
        )
    _memory["tick"] = tick

    intersections = state["intersections"]
    remaining = state["remaining_ticks"]
    rows = state["map"]["rows"]
    cols = state["map"]["cols"]

    coords = {iid: (ord(iid[0]) - 65, int(iid[1:]) - 1) for iid in intersections}
    grid = {rc: iid for iid, rc in coords.items()}
    link_occupancy = {}
    for info in state["links"].values():
        link_occupancy[(info["from"], info["to"])] = info["vehicles"]

    def neighbor(iid, direction):
        row, col = coords[iid]
        dr, dc = DELTA[direction]
        return grid.get((row + dr, col + dc))

    def hops_to_exit(iid, direction):
        row, col = coords[iid]
        return {"N": row + 1, "S": rows - row, "W": col + 1, "E": cols - col}[direction]

    def make_endgame(ticks, weight):
        def endgame_bonus(iid, direction, queue):
            if remaining >= ticks or queue == 0:
                return 0.0
            horizon = remaining - 6 * (hops_to_exit(iid, direction) - 1) - 6
            return weight * max(0, min(queue, horizon))
        return endgame_bonus

    # ---- Mode selection ----
    # The mode signal normalizes by arteries (rows+cols): queues live per
    # approach, and big grids otherwise dilute the congestion signal. Phase
    # lengths keep the per-intersection average (tuned separately).
    total_queued = sum(q for info in intersections.values() for q in info["queues"].values())
    per_intersection = total_queued / len(intersections)
    mode_signal = total_queued / (rows + cols)
    alpha = MODE_ALPHA_UP if mode_signal > _memory["ema"] else MODE_ALPHA_DOWN
    _memory["ema"] = _memory["ema"] * (1 - alpha) + alpha * mode_signal
    _memory["mode_age"] += 1
    if remaining < MODE_FREEZE:
        # Late mode flips reset the rhythm mid-flush and always measured worse.
        pass
    elif _memory["heavy"]:
        if _memory["mode_age"] >= MODE_DWELL and _memory["ema"] <= HEAVY_EXIT:
            _memory.update(heavy=False, mode_age=0)
    elif _memory["ema"] >= HEAVY_ENTER:
        # Seed the rhythm from the majority phase so entry is smooth.
        greens = [i["phase"] for i in intersections.values() if i["phase"] in AXIS_DIRECTIONS]
        majority = max(set(greens), key=greens.count) if greens else "NS_GREEN"
        _memory.update(heavy=True, mode_age=0, phase=majority, since=0)

    if not _memory["heavy"]:
        endgame_bonus = make_endgame(L_ENDGAME_TICKS, L_SAVABLE_WEIGHT)
        return _light(state, intersections, neighbor, link_occupancy, endgame_bonus)

    endgame_bonus = make_endgame(H_ENDGAME_TICKS, H_SAVABLE_WEIGHT)
    # ---- Heavy: synchronized global rhythm ----
    def movement_weight(iid, direction):
        queue = intersections[iid]["queues"][direction]
        upstream = neighbor(iid, OPPOSITE[direction])
        incoming = link_occupancy.get((upstream, iid), 0) if upstream else 0
        weight = queue + INCOMING_GREEN * incoming + endgame_bonus(iid, direction, queue)
        target = neighbor(iid, direction)
        if target is not None and H_BLOCK_DISCOUNT:
            # A movement whose outgoing link is full cannot use green time.
            space = 1.0 - link_occupancy.get((iid, target), 0) / 8.0
            weight *= 1.0 - H_BLOCK_DISCOUNT * max(0.0, 1.0 - space)
        return weight

    pressure = {
        axis: sum(movement_weight(iid, d) for iid in intersections for d in dirs)
        for axis, dirs in AXIS_DIRECTIONS.items()
    }
    current = _memory["phase"]
    other = "EW_GREEN" if current == "NS_GREEN" else "NS_GREEN"
    _memory["since"] += 1
    min_phase = min(MIN_PHASE_CAP, MIN_PHASE_BASE + MIN_PHASE_SLOPE * per_intersection)
    # A weak serving axis should not hold its green as long as a strong one:
    # scale the hold by the serving axis's share of *demand* (slow EMA, so the
    # signal reflects traffic asymmetry rather than the service cycle itself;
    # symmetric traffic gives share ~0.5 -> unchanged behavior).
    for axis in AXIS_DIRECTIONS:
        _memory["axis_ema"][axis] = (
            _memory["axis_ema"][axis] * (1 - SHARE_ALPHA) + SHARE_ALPHA * pressure[axis]
        )
    ema_total = _memory["axis_ema"][current] + _memory["axis_ema"][other]
    if ema_total > 0:
        share = _memory["axis_ema"][current] / ema_total
        min_phase = max(SHARE_FLOOR, min(MIN_PHASE_CAP, min_phase * SHARE_SCALE * share))
    if _memory["since"] >= min_phase:
        starved = any(
            intersections[iid]["queues"][d] > 0
            and intersections[iid]["oldest_wait"][d] >= H_STARVE
            for iid in intersections
            for d in AXIS_DIRECTIONS[other]
        )
        if starved or pressure[other] > pressure[current] * H_GAIN + H_MARGIN:
            _memory.update(phase=other, since=0)

    target = _memory["phase"]
    off_axis = "EW_GREEN" if target == "NS_GREEN" else "NS_GREEN"
    decisions = {}
    for iid, info in intersections.items():
        idle = all(
            info["queues"][d] == 0
            and link_occupancy.get((neighbor(iid, OPPOSITE[d]), iid), 0) == 0
            for d in AXIS_DIRECTIONS[target]
        )
        has_cross = any(info["queues"][d] > 0 for d in AXIS_DIRECTIONS[off_axis])
        decisions[iid] = off_axis if idle and has_cross else target
    return decisions


def _light(state, intersections, neighbor, link_occupancy, endgame_bonus):
    def movement(iid, direction, is_green):
        queue = intersections[iid]["queues"][direction]
        upstream = neighbor(iid, OPPOSITE[direction])
        incoming = link_occupancy.get((upstream, iid), 0) if upstream else 0
        target = neighbor(iid, direction)
        blocked = False
        downstream_load = 0
        if target is not None:
            occupancy = link_occupancy.get((iid, target), 0)
            downstream_load = intersections[target]["queues"][direction] + occupancy
            blocked = occupancy >= 8 or downstream_load >= L_BLOCK
        servable = queue > 0 and not blocked
        factor = INCOMING_GREEN if is_green else INCOMING_RED
        weight = queue + factor * incoming
        if blocked:
            return 0.05 * weight, servable
        weight = max(0.0, weight - L_DOWNSTREAM * downstream_load)
        return weight + endgame_bonus(iid, direction, queue), servable

    decisions = {}
    for iid, info in intersections.items():
        phase = info["phase"]
        green_axis = phase if phase in AXIS_DIRECTIONS else None
        pressure = {}
        servable = {}
        for axis, dirs in AXIS_DIRECTIONS.items():
            results = [movement(iid, d, axis == green_axis) for d in dirs]
            pressure[axis] = sum(weight for weight, _ in results)
            servable[axis] = sum(1 for _, s in results if s)
        if green_axis is None:
            decisions[iid] = max(pressure, key=pressure.get)
            continue
        other = "EW_GREEN" if green_axis == "NS_GREEN" else "NS_GREEN"
        switch = False
        if servable[green_axis] == 0 and servable[other] > 0:
            switch = pressure[other] > pressure[green_axis]
        elif pressure[other] > pressure[green_axis] * L_GAIN + L_MARGIN:
            switch = True
        elif servable[other] > 0:
            switch = any(
                info["queues"][d] > 0 and info["oldest_wait"][d] >= L_STARVE
                for d in AXIS_DIRECTIONS[other]
            )
        decisions[iid] = other if switch else green_axis
    return decisions
