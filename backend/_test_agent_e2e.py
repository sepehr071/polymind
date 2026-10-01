"""End-to-end agent path: tool loop + generate_image + final text."""
from __future__ import annotations

import json
import traceback

from app.extensions import db
from app.prompts.agent_orchestrator import AGENT_ORCHESTRATOR_PROMPT
from app.services import agent_service as asvc
from app.services.openrouter_service import OpenRouterService, ToolLoopPause


def main() -> int:
    model = asvc.orchestrator_model()
    tools = asvc.build_agent_tools(include_run_python=False)
    print("model", model)
    print("reasoning", asvc.reasoning_effort())
    print("subagent", asvc.subagent_enabled())
    print(
        "tools",
        [t.get("type") or t.get("function", {}).get("name") for t in tools],
    )

    def exec_tool(name, args):
        print("TOOL", name, json.dumps(args, ensure_ascii=False)[:200])
        if name == "ask_user":
            raise ToolLoopPause({"questions": args.get("questions")})
        if name == "generate_image":
            prompt = (args or {}).get("prompt") or "simple cat drawing"
            res = OpenRouterService.generate_image(
                prompt=prompt,
                model=asvc.image_model(),
                aspect_ratio="1:1",
                n=1,
                feature="agent",
                origin="web",
            )
            print("IMAGE ok=", res.get("success"), "err=", res.get("error"))
            if not res.get("success"):
                return f"[tool error] {res.get('error')}"
            return json.dumps(
                {"ok": True, "note": "Image generated and shown to the user."},
                ensure_ascii=False,
            )
        return f"[tool error] unknown {name}"

    with db.session_scope():
        try:
            res = OpenRouterService.run_tool_loop(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": "عکس میخوام بسازی — یک گربه ساده",
                    }
                ],
                tools=tools,
                tool_executor=exec_tool,
                system_prompt=AGENT_ORCHESTRATOR_PROMPT,
                max_rounds=5,
                temperature=0.3,
                max_tokens=4000,
                reasoning_effort=asvc.reasoning_effort(),
                feature="agent",
                origin="web",
                web_search=True,
                web_fetch=True,
            )
            print("finish", res.get("finish_reason"))
            print("error", res.get("error"))
            print("rounds", res.get("rounds"))
            content = (res.get("content") or "").strip()
            print("content_len", len(content))
            print("content", content[:500])
            if res.get("error"):
                return 2
            # success if we got tool use or non-empty content or clarify
            if res.get("finish_reason") == "clarify":
                print("CLARIFY ok", res.get("pause"))
                return 0
            if content or res.get("rounds", 0) > 0:
                print("E2E OK")
                return 0
            print("E2E EMPTY")
            return 1
        except Exception:
            traceback.print_exc()
            return 3


if __name__ == "__main__":
    raise SystemExit(main())
