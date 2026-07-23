"""Diagnostics: switch counts, unfinished vehicles, queue evolution."""

from __future__ import annotations

import sys
from pathlib import Path

from arena_eval import load_controller
from traffic_arena.engine import fixed_time_controller, run_scenario
from traffic_arena.scenarios import PUBLIC_SCENARIOS

ROOT = Path(__file__).resolve().parent


def diagnose(scenario, controller, label):
    result = run_scenario(scenario, controller, record_replay=True)
    frames = result.replay["frames"]
    switches = 0
    previous = {}
    for frame in frames:
        for iid, phase in frame["signals"].items():
            if iid in previous and phase.endswith("_YELLOW") and previous[iid].endswith("_GREEN"):
                switches += 1
            previous[iid] = phase
    metrics = result.metrics
    # queue proxy: waiting delta per tick at sample points
    samples = [frames[i]["waiting"] for i in range(0, len(frames), len(frames) // 10)]
    deltas = [b - a for a, b in zip(samples, samples[1:])]
    print(
        f"{label:12} cost={metrics.cost:>7} wait={metrics.wait_ticks:>7} "
        f"unfinished={metrics.unfinished:>4} (={metrics.unfinished * 300:>6}) "
        f"switches={switches:>4} wait-rate-per-decile={deltas}"
    )


def main():
    controller = load_controller(ROOT / (sys.argv[1] if len(sys.argv) > 1 else "controller.py"))
    for scenario in PUBLIC_SCENARIOS:
        print(f"--- {scenario.id} ({scenario.rows}x{scenario.cols})")
        diagnose(scenario, fixed_time_controller, "baseline")
        diagnose(scenario, controller, "controller")


if __name__ == "__main__":
    main()
