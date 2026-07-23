"""Explore fixed-cycle structure on public scenarios: phase length + offsets."""

from __future__ import annotations

from traffic_arena.engine import run_scenario
from traffic_arena.scenarios import PUBLIC_SCENARIOS


def make_fixed(phase_len, offset_per_row=0, offset_per_col=0, ns_share=0.5):
    cycle = round(phase_len / max(ns_share, 1 - ns_share))
    ns_len = round(cycle * ns_share)

    def controller(state):
        decisions = {}
        for iid in state["intersections"]:
            row = ord(iid[0]) - 65
            col = int(iid[1:]) - 1
            local = (state["tick"] + row * offset_per_row + col * offset_per_col) % cycle
            decisions[iid] = "NS_GREEN" if local < ns_len else "EW_GREEN"
        return decisions

    return controller


def main():
    for scenario in PUBLIC_SCENARIOS:
        print(f"--- {scenario.id}")
        for phase_len in (10, 13, 15, 18, 22, 26, 32, 40):
            cost = run_scenario(scenario, make_fixed(phase_len), record_replay=False).metrics.cost
            print(f"  phase={phase_len:>2} cost={cost}")
        print("  offsets (phase=15):")
        for off_row, off_col in ((5, 0), (0, 5), (5, 5), (-5, 0), (0, -5), (7, 7), (-5, -5), (5, -5)):
            cost = run_scenario(
                scenario, make_fixed(15, off_row, off_col), record_replay=False
            ).metrics.cost
            print(f"  row_off={off_row:>2} col_off={off_col:>2} cost={cost}")


if __name__ == "__main__":
    main()
