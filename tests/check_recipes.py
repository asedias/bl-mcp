"""Checks the recipes against the registered tools. No Blender needed.

uv run python tests/check_recipes.py
Reads every backticked span of every recipe and prompt: `tool`, `tool(param=...)`, `param=value`, `param`, `topic-id`.
"""

import asyncio
import re
import sys

import bl_mcp.server  # noqa: F401  registers every tool and prompt
from bl_mcp import tools_recipes
from bl_mcp.app import mcp

ANSWER_FIELDS = {
    "warning", "warnings", "hint", "inner_detail", "achieved_width", "clamped", "excluded", "ready", "tiny_gaps",
    "boxes_used", "not_exported", "faces_without_material", "clipped_highlights", "crushed_blacks", "rejected",
    "visible_share", "auto_exposure", "textures", "ignored_options",
}

SPAN = re.compile(r"`([^`\n]+)`")
IDENT = r"[a-z][a-z0-9_]*"
KEYWORD = re.compile(rf"(?<![\w'\"])({IDENT})\s*=")
TOPIC = re.compile(r"[a-z]+(-[a-z]+)+")


def parse(span):
    """(tool or None, parameters, bare identifier or None) of one backticked span."""
    call = re.fullmatch(rf"({IDENT})\((.*)\)", span)
    if call:
        return call.group(1), KEYWORD.findall(call.group(2)), None
    keyword = re.fullmatch(rf"({IDENT})=.*", span)
    if keyword:
        return None, [keyword.group(1)], None
    return None, [], span if re.fullmatch(IDENT, span) else None


def check(source, text, tools, topics):
    every_parameter = set().union(*tools.values())
    errors = []
    for span in SPAN.findall(text):
        tool, parameters, bare = parse(span)
        if TOPIC.fullmatch(span) and span not in topics:
            errors.append(f"{source}: `{span}` is not a recipe topic")
        if tool:
            if tool not in tools:
                errors.append(f"{source}: `{tool}` is not a tool")
                continue
            errors += [f"{source}: `{tool}` has no parameter `{parameter}`" for parameter in parameters if parameter not in tools[tool]]
        elif parameters and parameters[0] not in every_parameter:
            errors.append(f"{source}: `{parameters[0]}` is not a parameter of any tool")
        elif bare and bare not in every_parameter and bare not in ANSWER_FIELDS and bare not in tools:
            errors.append(f"{source}: `{bare}` is not a tool, a parameter or a known answer field")
    return errors


async def registered():
    tools = {tool.name: set(tool.inputSchema.get("properties", {})) for tool in await mcp.list_tools()}
    prompts = {}
    for prompt in await mcp.list_prompts():
        arguments = {argument.name: "1" for argument in prompt.arguments or []}
        result = await mcp.get_prompt(prompt.name, arguments)
        prompts[prompt.name] = "\n".join(message.content.text for message in result.messages)
    return tools, prompts


def main():
    tools, prompts = asyncio.run(registered())
    topics = tools_recipes.topics()
    errors = []
    if "recipe" not in tools:
        errors.append("the tool `recipe` is not registered")
    listing = tools_recipes.recipe()
    for topic, summary in topics.items():
        text = tools_recipes.recipe(topic)
        lines = len((tools_recipes.RECIPES / f"{topic}.md").read_text(encoding="utf-8").splitlines())
        print(f"ok   {topic}: {lines} lines in the file, {len(text.splitlines())} lines served")
        if not summary:
            errors.append(f"{topic}: the first line is not 'summary: ...'")
        if f"{topic}: {summary}" not in listing:
            errors.append(f"{topic}: missing from the topic list")
        if topic != tools_recipes.RULES and tools_recipes.RULES not in text:
            errors.append(f"{topic}: served without the rules and without a pointer to them")
        errors += check(f"recipe {topic}", text if topic == tools_recipes.RULES else tools_recipes.section(topic, summary), tools, topics)
    try:
        tools_recipes.recipe("no-such-topic")
        errors.append("an unknown topic gives no error")
    except ValueError as error:
        if not all(topic in str(error) for topic in topics):
            errors.append("the error of an unknown topic does not list the topics")
    for name, text in prompts.items():
        print(f"ok   prompt {name}: {len(text.splitlines())} lines")
        if not any(tools_recipes.section(topic, summary) in text for topic, summary in topics.items()):
            errors.append(f"prompt {name}: not built from a recipe")
        errors += check(f"prompt {name}", text.split("\n\n", 1)[0], tools, topics)

    for line in sorted(set(errors)):
        print("FAIL", line)
    print("FAILED" if errors else "ALL PASSED", f"{len(topics)} recipes, {len(prompts)} prompts, {len(tools)} tools")
    sys.exit(1 if errors else 0)


main()
