import json
import sys
import intent_check


def load_plan(path):
    with open(path) as f:
        return json.load(f)


def extract_changes(plan):
    changes = []

    for rc in plan.get("resource_changes", []):
        actions = rc["change"]["actions"]

        if actions == ["no-op"]:
            continue

        changes.append({
            "address": rc["address"],
            "type": rc["type"],
            "actions": actions,
            "replace_paths": rc["change"].get("replace_paths", []),
            "reason": rc.get("action_reason", ""),
            "diffs": diff_attributes(rc),
        })

    return changes


def build_dependency_map(plan):
    """Who depends on whom. Returns {resource: [things it needs]}."""
    deps = {}

    resources = (
        plan.get("configuration", {})
            .get("root_module", {})
            .get("resources", [])
    )

    for res in resources:
        address = res["address"]
        needs = set()

        for expr in res.get("expressions", {}).values():
            if isinstance(expr, dict):
                for ref in expr.get("references", []):
                    # "aws_dynamodb_table.sessions.arn" -> "aws_dynamodb_table.sessions"
                    parts = ref.split(".")
                    if len(parts) >= 2:
                        needs.add(f"{parts[0]}.{parts[1]}")

        needs.discard(address)
        deps[address] = sorted(needs)

    return deps


def find_dependents(target, deps):
    """Who breaks if `target` is destroyed? Walks the chain."""
    affected = set()
    queue = [target]

    while queue:
        current = queue.pop()

        for resource, needs in deps.items():
            if current in needs and resource not in affected:
                affected.add(resource)
                queue.append(resource)

    return sorted(affected)


def label(actions):
    if actions == ["create"]:
        return "CREATE"
    if actions == ["update"]:
        return "UPDATE"
    if actions == ["delete"]:
        return "DELETE"
    if set(actions) == {"create", "delete"}:
        return "REPLACE"
    return "/".join(actions)

NOISE_FIELDS = {
    "id", "arn", "tags_all", "unique_id", "create_date",
    "name_prefix", "owner_id", "hosted_zone_id",
    "bucket_domain_name", "bucket_regional_domain_name",
}


def diff_attributes(rc):
    """Return the fields that actually changed inside a resource."""
    before = rc["change"].get("before") or {}
    after = rc["change"].get("after") or {}

    diffs = []

    for key in sorted(set(before) | set(after)):
        if key in NOISE_FIELDS:
            continue

        old = before.get(key)
        new = after.get(key)

        if old == new:
            continue

        # after=None usually means "unknown until applied", not a real change
        if new is None and old is not None:
            continue

        diffs.append({
            "field": key,
            "before": summarise(old),
            "after": summarise(new),
        })

    return diffs


def summarise(value):
    """Keep values short so we don't blow up the token count."""
    if value is None:
        return "null"

    text = json.dumps(value) if isinstance(value, (dict, list)) else str(value)

    if len(text) > 300:
        return text[:300] + "...(truncated)"

    return text
def main():
    plan_path = sys.argv[1]
    intent = sys.argv[2]
    use_real_ai = "--real" in sys.argv

    plan = load_plan(plan_path)
    changes = extract_changes(plan)
    deps = build_dependency_map(plan)

    for c in changes:
        c["dependents"] = find_dependents(c["address"], deps)
    if "--debug" in sys.argv:
        print("\n--- MESSAGE SENT TO MODEL ---")
        print(intent_check.build_user_message(intent, changes))
        print("--- END ---\n")
    print(f"\nSTATED INTENT: {intent}")
    print(f"\nDETERMINISTIC SCAN — {len(changes)} changing resource(s):\n")

    for c in changes:
        tag = label(c["actions"])
        print(f"  [{tag}]  {c['address']}")

        if tag == "REPLACE":
            attrs = [p[0] for p in c["replace_paths"] if p]
            print(f"     caused by: {', '.join(attrs)}")
            if c["dependents"]:
                print(f"     blast radius: {len(c['dependents'])} dependent(s)")
                for d in c["dependents"]:
                    print(f"        - {d}")

    print("\nINTENT CHECK:\n")

    if use_real_ai:
        raw = intent_check.ask_model(intent, changes)
    else:
        raw = intent_check.fake_model(intent, changes)

    try:
        result = intent_check.parse_response(raw)
    except Exception as e:
        print(f"  Could not parse model response: {e}")
        print(f"  Raw: {raw}")
        return

    print(f"  VERDICT: {result['verdict'].upper()}")
    print(f"  {result['summary']}\n")

    for item in result.get("unexplained", []):
        print(f"  ! {item['resource']}")
        print(f"    {item['why']}")

    print()
if __name__ == "__main__":
    main()