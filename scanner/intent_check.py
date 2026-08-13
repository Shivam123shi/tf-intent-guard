import json
import boto3

REGION = "ap-south-1"
MODEL_ID = "apac.amazon.nova-lite-v1:0"

SYSTEM_PROMPT = """You review Terraform pull requests. Your job is to find
changes the author did not tell anyone about.

You get: the author's stated intent, and the changes the plan will make.

Evaluate EVERY change against this procedure, in order:

STEP 1 - Is it marked [CASCADE]?
   Yes -> skip it. It is an automatic knock-on effect. Judge the root change.
   No  -> continue.

STEP 2 - Is it destructive (delete, or delete/create)?
   Yes -> Does the intent EXPLICITLY ask to delete, remove, decommission,
          drop, replace, or destroy this resource?
            Yes -> expected, not a finding.
            No  -> DIVERGED. This is a finding.
          Beware the rename trap. If the intent describes a rename, a move,
          a resize, or any other modification, and the plan achieves it by
          destroying and recreating the resource, that is DIVERGED. The
          author asked for a modification and is getting a deletion. The
          fact that the field diff matches the intent word for word does
          not matter - what matters is that data will be destroyed and the
          intent never said so.

          Only treat destruction as expected when the intent uses explicit
          removal language: delete, remove, decommission, drop, destroy,
          tear down, wipe. "Rename", "update", "change", and "move" are
          NOT removal language.
   No  -> continue to step 3.

STEP 3 - It is a non-destructive update. Does the intent refer to this
   resource and explain why this field is changing?
     Yes -> expected, not a finding.
     No  -> DIVERGED. This is a finding.
   Watch permission scope especially: IAM policy documents, security group
   rules, public access settings. A widening scope needs explicit
   justification in the intent.

Verdict is "diverged" if there is at least one finding, otherwise "aligned".
List each resource at most once in unexplained.

Reply with ONLY valid JSON, no markdown fences:
{
  "verdict": "aligned" | "diverged",
  "unexplained": [
     {"resource": "...", "why": "one short sentence"}
  ],
  "summary": "one sentence for the PR reviewer"
}"""

def build_user_message(intent, changes):
    # Map each resource to the thing that dragged it in
    caused_by = {}
    for c in changes:
        for dep in c.get("dependents", []):
            caused_by[dep] = c["address"]

    lines = []
    for c in changes:
        line = f"- {c['address']}: {'/'.join(c['actions'])}"

        if c.get("replace_paths"):
            attrs = [p[0] for p in c["replace_paths"] if p]
            line += f" (forced by attribute: {', '.join(attrs)})"

        if c["address"] in caused_by:
            line += f" [CASCADE: only changing because {caused_by[c['address']]} is being replaced]"

        if c.get("dependents"):
            line += f" [{len(c['dependents'])} resource(s) depend on this]"

        lines.append(line)

        for d in c.get("diffs", [])[:6]:
            lines.append(f"    {d['field']}: {d['before']}  =>  {d['after']}")

    return f"""STATED INTENT:
{intent}

PLANNED CHANGES:
{chr(10).join(lines)}"""


def ask_model(intent, changes):
    client = boto3.client("bedrock-runtime", region_name=REGION)

    response = client.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{
            "role": "user",
            "content": [{"text": build_user_message(intent, changes)}]
        }],
        inferenceConfig={"maxTokens": 600, "temperature": 0}
    )

    return response["output"]["message"]["content"][0]["text"]


def fake_model(intent, changes):
    """Stand-in while Bedrock quota is exhausted."""
    return json.dumps({
        "verdict": "diverged",
        "unexplained": [{
            "resource": "aws_dynamodb_table.sessions",
            "why": "Renaming a field does not require destroying the table."
        }],
        "summary": "This PR destroys a database, which the stated intent does not mention."
    })


def parse_response(raw):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)