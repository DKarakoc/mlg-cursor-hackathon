"""Grid-search controller module constants against the public scenarios."""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

from traffic_arena.engine import run_scenario
from traffic_arena.scenarios import PUBLIC_SCENARIOS
from traffic_arena.score_profiles import score_profile
from traffic_arena.scoring import geometric_mean, scenario_score

ROOT = Path(__file__).resolve().parent


def load_module():
    spec = importlib.util.spec_from_file_location("team_controller", ROOT / "controller.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(module, scenario_filter=None):
    scores = []
    costs = []
    for scenario in PUBLIC_SCENARIOS:
        if scenario_filter and scenario.id not in scenario_filter:
            continue
        result = run_scenario(scenario, module.control, record_replay=False)
        profile = score_profile(scenario.id)
        scores.append(scenario_score(result.metrics.cost, profile.baseline_cost, profile.target_cost))
        costs.append(result.metrics.cost)
    return geometric_mean(scores), costs, scores


def main():
    # knob=value1,value2 ... [--only scenario_id]
    grid = {}
    only = None
    args = sys.argv[1:]
    index = 0
    while index < len(args):
        if args[index] == "--only":
            only = {args[index + 1]}
            index += 2
            continue
        knob, values = args[index].split("=")
        grid[knob] = [float(v) if "." in v else int(v) for v in values.split(",")]
        index += 1

    module = load_module()
    keys = list(grid)
    best = None
    for combo in itertools.product(*(grid[k] for k in keys)):
        for key, value in zip(keys, combo):
            setattr(module, key, value)
        total, costs, scores = evaluate(module, only)
        label = " ".join(f"{k}={v}" for k, v in zip(keys, combo))
        print(f"{label:60} geomean={total:>7,} costs={costs} scores={scores}")
        if best is None or total > best[0]:
            best = (total, label)
    print(f"\nBEST: {best[1]} -> {best[0]:,}")


if __name__ == "__main__":
    main()
