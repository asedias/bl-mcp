from pathlib import Path

from .app import mcp

RECIPES = Path(__file__).parent / "recipes"
RULES = "rules"
MAX_LINES_WITH_RULES = 120


def topics():
    """Topic id to summary, read from the recipe files on every call."""
    found = {}
    for path in sorted(RECIPES.glob("*.md"), key=lambda p: (p.stem != RULES, p.stem)):
        first_line = path.read_text(encoding="utf-8").split("\n", 1)[0]
        found[path.stem] = first_line.removeprefix("summary:").strip()
    return found


def section(topic, summary):
    body = (RECIPES / f"{topic}.md").read_text(encoding="utf-8").split("\n", 1)[1].strip()
    return f"# {topic}: {summary}\n\n{body}"


def recipe_text(topic):
    """One recipe with the rules in front, or with a pointer to them when both are too long together."""
    known = topics()
    if topic not in known:
        raise ValueError(f"Unknown topic {topic!r}. Topics: {', '.join(known)}.")
    text = section(topic, known[topic])
    if topic == RULES or RULES not in known:
        return text
    with_rules = f"{section(RULES, known[RULES])}\n\n{text}"
    if len(with_rules.splitlines()) <= MAX_LINES_WITH_RULES:
        return with_rules
    return f"Read recipe(topic='{RULES}') first: the universal rules.\n\n{text}"


@mcp.tool()
def recipe(topic: str | None = None) -> str:
    """Step-by-step recipe for a task: the tool calls in order, the numbers to check and the known traps.
    Call it before a task of these kinds: a character from reference images, a hard-surface prop, a weapon or object
    from an orthographic sheet, a scene from a perspective photo, a level blockout, materials and a final render,
    export for a game. Without `topic` it lists the topics, one line each. With a topic it returns the universal rules
    and that recipe. An unknown topic is an error that lists the topics. It works when Blender is closed."""
    if topic is None:
        lines = [f"{name}: {summary}" for name, summary in topics().items()]
        return "\n".join(["Topics. Call recipe(topic=...) for one.", *lines])
    return recipe_text(topic.strip())
