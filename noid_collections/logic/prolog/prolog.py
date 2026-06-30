"""
logic:prolog — executes SWI-Prolog goals via PySwip.

Static facts and rules can be baked into the `facts_rules` property.  The
`query` notice supplies additional facts/rules to merge at call time, plus the
goal to execute.  This lets other pipeline components (e.g. lm:ner) inject
dynamically-derived facts.

Properties:
  facts_rules — Prolog program text loaded before every query (default: "")

Receives:
  query → {
      "query":       str,   # Prolog goal, with or without "?-" prefix / "." suffix
      "facts_rules": str,   # (optional) extra clauses to append before the goal
  }
  or plain string treated as the goal, with no extra facts.

Publishes:
  result → {
      "query":          str,
      "solutions":      [{var: value, ...}, ...],
      "solution_count": int,
  }
  error  → {"query": str, "message": str}

Requires: pyswip>=0.2.10 + SWI-Prolog installed on the system.
          pip install pyswip

Scene usage example:
  {
    "type": "logic:prolog",
    "properties": {
      "facts_rules": "mortal(X) :- human(X).\\nhuman(socrates)."
    },
    "subscribe": "pipeline/prolog-in~query",
    "publish":   "result~pipeline/prolog-out;error~pipeline/prolog-error"
  }
"""
import os
import tempfile

from noid.core.component import Noid, OidComponent


def _clean_value(val):
    """Recursively convert PySwip atoms/functors to plain Python types."""
    if isinstance(val, bytes):
        return val.decode("utf-8")
    if isinstance(val, list):
        return [_clean_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _clean_value(v) for k, v in val.items()}
    type_name = type(val).__name__
    if type_name in ("Atom", "Functor", "Variable"):
        return str(val)
    return val


def _normalize_query(raw: str) -> str:
    q = raw.strip()
    if q.startswith("?-"):
        q = q[2:].strip()
    if q.endswith("."):
        q = q[:-1].strip()
    return q


def _run_prolog(program: str, goal: str) -> list:
    """Write program to a temp file, consult it, run goal, return solutions."""
    try:
        from pyswip import Prolog
    except ImportError as exc:
        raise RuntimeError(
            "pyswip package (and SWI-Prolog) are required: pip install pyswip"
        ) from exc

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pl", delete=False, encoding="utf-8"
    ) as f:
        f.write(program)
        tmp_path = f.name

    try:
        prolog = Prolog()
        safe_path = tmp_path.replace("\\", "/")
        list(prolog.query(f"consult('{safe_path}')"))
        solutions = list(prolog.query(goal))
        return [_clean_value(s) for s in solutions]
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@Noid.component({
    "id": "logic:prolog",
    "name": "Prolog",
    "description": (
        "Executes SWI-Prolog goals via PySwip and publishes unified solutions. "
        "Static facts and rules can be baked into the facts_rules property; "
        "dynamic facts can be injected per-query."
    ),
    "properties": {
        "facts_rules": {
            "default": "",
            "kind": "text",
            "description": "Prolog program text (facts and rules) loaded before every query.",
        },
    },
    "receive": {
        "query": {
            "description": (
                "Prolog goal to execute. Payload keys: query (str, the goal), "
                "facts_rules (str, optional extra clauses). Also accepts a plain goal string."
            ),
        },
    },
    "publish": "result~prolog/result;error~prolog/error;done~prolog/done",
    "output_notices": {
        "result": {
            "description": (
                "Successful solutions. Keys: query (str), "
                "solutions (list of variable-binding dicts), solution_count (int)."
            ),
        },
        "error": {
            "description": "Query failed or threw an exception. Keys: query (str), message (str).",
        },
        "done": {
            "description": "Always emitted after result or error, signaling completion.",
        },
    },
})
class PrologAgentOid(OidComponent):
    """Executes a Prolog goal and publishes unified solutions."""

    async def handle_query(self, notice: str, message) -> None:
        if isinstance(message, dict):
            raw_goal = message.get("query", "").strip()
            extra_clauses = message.get("facts_rules", "").strip()
        else:
            raw_goal = str(message).strip()
            extra_clauses = ""

        if not raw_goal:
            return

        goal = _normalize_query(raw_goal)

        program_parts = []
        if self.facts_rules and self.facts_rules.strip():
            program_parts.append(self.facts_rules.strip())
        if extra_clauses:
            program_parts.append(extra_clauses)
        program = "\n".join(program_parts)

        try:
            solutions = _run_prolog(program, goal)
            await self._notify("result", {
                "query":          goal,
                "solutions":      solutions,
                "solution_count": len(solutions),
            })
        except Exception as exc:
            await self._notify("error", {"query": goal, "message": str(exc)})
        await self._notify("done", {})
