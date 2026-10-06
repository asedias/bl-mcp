"""Runs any OpenAI-compatible chat model as an agent on the real MCP server and logs every call.

uv run python tests/agent_run.py --env path/to/model.env --task task.md --out runs/name
The env file has BASE_URL, API_KEY and MODEL (a prefix such as MIMO_ is fine). The log is JSONL plus a summary.
Point BL_MCP_PORT at a private Blender (tests/serve_headless.py) to keep your own Blender untouched.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent


def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith(("MIMO_", "LLM_")):
                key = key.split("_", 1)[1]
            values[key] = value.strip().strip('"')
    missing = [k for k in ("BASE_URL", "API_KEY", "MODEL") if k not in values]
    if missing:
        sys.exit(f"{path} lacks {missing}")
    return values


def as_function(tool):
    return {"type": "function", "function": {"name": tool.name, "description": tool.description or "", "parameters": tool.inputSchema}}


def trim_old_results(messages, keep_recent, limit=400):
    """Old tool answers shrink to their head, so a long run does not grow the prompt without bound."""
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    for message in tool_messages[:-keep_recent]:
        if len(message["content"]) > limit:
            message["content"] = message["content"][:limit] + " …(trimmed)"


class Chat:
    def __init__(self, env):
        base = env["BASE_URL"].rstrip("/")
        self.url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {env['API_KEY']}", "Content-Type": "application/json"}
        self.model = env["MODEL"]
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0}
        self.client = httpx.Client(timeout=600)

    def ask(self, messages, tools):
        body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0.2}
        last = None
        for attempt in range(8):
            try:
                response = self.client.post(self.url, headers=self.headers, json=body)
            except httpx.HTTPError as error:
                last = error.__class__.__name__
            else:
                if response.status_code < 500 and response.status_code != 429:
                    break
                last = f"{response.status_code}: {response.text[:200]}"
            # A network outage can last minutes: wait up to 5 minutes between attempts.
            pause = min(300, 15 * 2**attempt)
            print(f"request failed ({last}), retry {attempt + 1} in {pause} s", flush=True)
            time.sleep(pause)
        else:
            raise RuntimeError(f"the model endpoint did not answer eight times; last: {last}")
        if response.status_code != 200:
            raise RuntimeError(f"{response.status_code}: {response.text[:800]}")
        data = response.json()
        usage = data.get("usage") or {}
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0)
        self.usage["requests"] += 1
        return data["choices"][0]["message"]


async def call_tool(session, name, arguments, with_images):
    try:
        result = await session.call_tool(name, arguments)
    except Exception as error:  # the server reports unknown tools and bad arguments this way
        return f"error: {error}", [], True
    text = "\n".join(c.text for c in result.content if c.type == "text") or "(no text)"
    images = [c for c in result.content if c.type == "image"] if with_images else []
    return text, images, bool(result.isError)


async def loop(args, chat, session, tools, messages, log, counts):
    for step in range(args.max_steps):
        trim_old_results(messages, args.keep_recent)
        message = chat.ask(messages, tools)
        messages.append(message)
        tool_calls = message.get("tool_calls") or []
        if message.get("content"):
            print(f"[{step}] model: {message['content'][:300].replace(chr(10), ' ')}", flush=True)
        if not tool_calls:
            return
        pictures = []
        for call in tool_calls:
            name = call["function"]["name"]
            t0 = time.time()
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError as error:
                arguments, text, images, is_error = {}, f"arguments are not JSON: {error}", [], True
            else:
                text, images, is_error = await call_tool(session, name, arguments, args.images)
            counts["calls"] += 1
            counts["errors"] += is_error
            print(f"[{step}] {'FAIL' if is_error else 'ok  '} {name} {json.dumps(arguments)[:120]} -> {text[:100].replace(chr(10), ' ')}", flush=True)
            log.write(json.dumps({"step": step, "tool": name, "arguments": arguments, "error": is_error, "result": text[:4000], "images": len(images), "seconds": round(time.time() - t0, 2)}) + "\n")
            log.flush()
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": text[: args.max_result]})
            pictures += [{"type": "image_url", "image_url": {"url": f"data:{image.mimeType};base64,{image.data}"}} for image in images]
        if pictures:
            messages.append({"role": "user", "content": [{"type": "text", "text": f"Pictures returned by the last tools ({len(pictures)})."}, *pictures[:4]]})
    print("step limit reached", flush=True)


async def run(args):
    env = read_env(args.env)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "log.jsonl").open("w")
    chat = Chat(env)
    task = Path(args.task).read_text()
    forwarded = {k: os.environ[k] for k in ("BL_MCP_PORT", "BL_MCP_WORK", "BL_MCP_TOOLSETS") if k in os.environ}
    params = StdioServerParameters(command="uv", args=["run", "--project", str(HERE.parent), "bl-mcp"], env=forwarded or None)
    started = time.time()
    counts, failure, messages = {"calls": 0, "errors": 0}, None, []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = [as_function(t) for t in (await session.list_tools()).tools]
            system = (init.instructions or "") + ("\n\n" + Path(args.skill).read_text() if args.skill else "")
            messages += [{"role": "system", "content": system}, {"role": "user", "content": task}]
            try:
                await loop(args, chat, session, tools, messages, log, counts)
            except Exception as error:  # the summary is written even when the run breaks
                failure = f"{error.__class__.__name__}: {error}"
                print("run failed:", failure, flush=True)
    summary = {
        "model": chat.model,
        "failure": failure,
        "requests": chat.usage["requests"],
        "prompt_tokens": chat.usage["prompt_tokens"],
        "completion_tokens": chat.usage["completion_tokens"],
        "tool_calls": counts["calls"],
        "tool_errors": counts["errors"],
        "minutes": round((time.time() - started) / 60, 1),
        "final_message": messages[-1].get("content") if messages else None,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (out / "transcript.json").write_text(json.dumps([m for m in messages if m.get("role") != "system"], indent=1, ensure_ascii=False, default=str))
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--skill", default=str(HERE.parent / "skills" / "bl-mcp" / "SKILL.md"))
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--max-result", type=int, default=12000, help="characters of a tool answer given to the model")
    parser.add_argument("--keep-recent", type=int, default=30, help="tool answers kept in full; older ones are trimmed")
    parser.add_argument("--no-images", dest="images", action="store_false")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
