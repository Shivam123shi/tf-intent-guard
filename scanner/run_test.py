import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parse_plan
import intent_check

RUNS = 5


def prepare(case):
    """Parse the plan once - it never changes between runs."""
    plan = parse_plan.load_plan(case["plan_file"])
    changes = parse_plan.extract_changes(plan)
    deps = parse_plan.build_dependency_map(plan)

    for c in changes:
        c["dependents"] = parse_plan.find_dependents(c["address"], deps)

    return changes


def one_run(intent, changes, use_real):
    if use_real:
        raw = intent_check.ask_model(intent, changes)
    else:
        raw = intent_check.fake_model(intent, changes)

    try:
        return intent_check.parse_response(raw)["verdict"]
    except Exception:
        return "PARSE_ERROR"


def main():
    use_real = "--real" in sys.argv

    with open("testcases/cases.json") as f:
        cases = json.load(f)

    print(f"\n{len(cases)} cases x {RUNS} runs each\n")

    results = []

    for case in cases:
        changes = prepare(case)
        expected = case["expected"]
        verdicts = []

        for i in range(RUNS):
            verdicts.append(one_run(case["intent"], changes, use_real))
            if use_real:
                time.sleep(1.5)

        hits = verdicts.count(expected)
        rate = hits / RUNS

        if rate == 1.0:
            mark = "STABLE PASS"
        elif rate == 0.0:
            mark = "STABLE FAIL"
        else:
            mark = "UNSTABLE   "

        print(f"  {mark}  {hits}/{RUNS}  {case['name']}")

        if rate < 1.0:
            print(f"              got: {', '.join(verdicts)}")

        results.append(rate)

    overall = sum(results) / len(results)
    stable_pass = sum(1 for r in results if r == 1.0)

    print(f"\n  Overall accuracy: {overall:.0%}")
    print(f"  Fully stable cases: {stable_pass}/{len(results)}\n")


if __name__ == "__main__":
    main()