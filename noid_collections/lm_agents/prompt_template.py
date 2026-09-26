"""
Prompt template rendering shared by the lm agents (lm:lm-agent, lm:image-agent).

Placeholders use double braces so they never collide with literal JSON in a template:
  {{input}}    — message["content"] (or the message itself when it is a plain string)
  {{question}} — message["question"]
  {{key}}      — any flat message key
  {{row.name}} — dot-separated path into nested fields
Unknown placeholders render as an empty string.
"""
import re


def render_prompt(template: str, message) -> str:
    """Render template against a bus message (dict or plain string)."""
    content = message.get("content", "") if isinstance(message, dict) else str(message)
    question = message.get("question", "") if isinstance(message, dict) else ""
    return render_template(template, content, question, message)


def render_template(template: str, input_val: str, question: str, message) -> str:
    # Callable replacements: a plain string would have its backslashes parsed as
    # regex escapes (e.g. a Windows path in the content raises "bad escape").
    result = re.sub(re.escape("{{input}}"), lambda _: input_val, template, flags=re.IGNORECASE)
    result = re.sub(re.escape("{{question}}"), lambda _: question, result, flags=re.IGNORECASE)
    if isinstance(message, dict):
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key in message:
                return str(message[key])
            return resolve_path(message, key)
        result = re.sub(r"\{\{([^}]+)\}\}", _replace, result)
    return result


def resolve_path(obj: dict, path: str) -> str:
    """Walk a dot-separated path in a nested dict; return str value or empty string."""
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return ""
        current = current[part]
    return str(current)
