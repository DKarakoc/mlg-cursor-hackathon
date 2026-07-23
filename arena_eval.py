"""Local evaluation harness: public scenarios + randomized robustness suite."""

from __future__ import annotations

import argparse
import importlib.util
import random
import sys
import time
from pathlib import Path

from traffic_arena.engine import fixed_time_controller, run_scenario
from traffic_arena.scenarios import DemandWindow, Scenario, PUBLIC_SCENARIOS
from traffic_arena.score_profiles import score_profile
from traffic_arena.scoring import geometric_mean, scenario_score

ROOT = Path(__file__).resolve().parent


def load_controller(path: Path):
    spec = importlib.util.spec_from_file_location("team_controller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.control


def eval_public(controller) -> list[int]:
    scores = []
    print(f"{'scenario':22} {'cost':>8} {'baseline':>9} {'gold':>8} {'score':>7}  gap-to-gold")
    for scenario in PUBLIC_SCENARIOS:
        start = time.perf_counter()
        result = run_scenario(scenario, controller, record_replay=False)
        elapsed = time.perf_counter() - start
        profile = score_profile(scenario.id)
        score = scenario_score(result.metrics.cost, profile.baseline_cost, profile.target_cost)
        scores.append(score)
        gap = result.metrics.cost - profile.target_cost
        print(
            f"{scenario.id:22} {result.metrics.cost:>8} {profile.baseline_cost:>9} "
            f"{profile.target_cost:>8} {score:>7,}  {gap:+d} ({elapsed:.1f}s)"
        )
    print(f"{'PUBLIC GEOMEAN':22} {'':>8} {'':>9} {'':>8} {geometric_mean(scores):>7,}")
    return scores


def random_scenario(rng: random.Random, index: int) -> Scenario:
    rows = rng.randint(1, 4)
    cols = rng.randint(1, 4)
    ticks = 900
    n_windows = rng.randint(1, 4)
    cuts = sorted(rng.sample(range(100, ticks - 50, 50), n_windows - 1)) if n_windows > 1 else []
    bounds = [0, *cuts, ticks]
    windows = []
    for start, end in zip(bounds, bounds[1:]):
        # Skewed demand: pick a dominant direction some of the time.
        rates = {d: rng.uniform(0.03, 0.20) for d in "NSEW"}
        if rng.random() < 0.6:
            rates[rng.choice("NSEW")] = rng.uniform(0.2, 0.42)
        row_weights = ()
        col_weights = ()
        if rng.random() < 0.4:
            row_weights = tuple(rng.choice((0.4, 1.0, 1.0, 2.2)) for _ in range(rows))
        if rng.random() < 0.4:
            col_weights = tuple(rng.choice((0.4, 1.0, 1.0, 2.2)) for _ in range(cols))
        windows.append(
            DemandWindow(
                start, end,
                north_rate=rates["N"], south_rate=rates["S"],
                east_rate=rates["E"], west_rate=rates["W"],
                row_weights=row_weights, col_weights=col_weights,
            )
        )
    return Scenario(
        f"random-{index}", f"Random {index}", rows, cols,
        seed=rng.randrange(1, 10**6), ticks=ticks,
        link_capacity=rng.choice((6, 8, 8, 10)),
        demand_windows=tuple(windows),
    )


def eval_random(controller, count: int, seed: int) -> None:
    rng = random.Random(seed)
    ratios = []
    est_scores = []
    print(f"\n{'scenario':14} {'grid':>5} {'cost':>8} {'baseline':>9} {'ratio':>6}  est-score")
    for index in range(count):
        scenario = random_scenario(rng, index)
        baseline = run_scenario(scenario, fixed_time_controller, record_replay=False)
        result = run_scenario(scenario, controller, record_replay=False)
        ratio = result.metrics.cost / baseline.metrics.cost
        ratios.append(ratio)
        # Estimate gold at 78% of baseline cost (matches harder public profiles).
        gold = max(1, round(baseline.metrics.cost * 0.78))
        if baseline.metrics.cost <= gold:
            gold = baseline.metrics.cost - 1
        est = scenario_score(result.metrics.cost, baseline.metrics.cost, gold)
        est_scores.append(est)
        print(
            f"random-{index:<7} {scenario.rows}x{scenario.cols:>3} {result.metrics.cost:>8} "
            f"{baseline.metrics.cost:>9} {ratio:>6.3f}  {est:>7,}"
        )
    ratios.sort()
    print(
        f"\nratios: best={ratios[0]:.3f} median={ratios[len(ratios) // 2]:.3f} "
        f"worst={ratios[-1]:.3f} mean={sum(ratios) / len(ratios):.3f}"
    )
    print(f"est geomean={geometric_mean(est_scores):,}  est min={min(est_scores):,}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller", default=str(ROOT / "controller.py"))
    parser.add_argument("--random", type=int, default=0, help="also run N random scenarios")
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()
    controller = load_controller(Path(args.controller))
    eval_public(controller)
    if args.random:
        eval_random(controller, args.random, args.seed)


if __name__ == "__main__":
    main()
