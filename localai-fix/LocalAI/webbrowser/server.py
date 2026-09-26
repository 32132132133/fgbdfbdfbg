"""Playwright MCP(마이크로소프트) 프록시 — 로컬 모델용으로 핵심 도구만 남기고 긴 결과는 자른다."""
import os, sys, asyncio, json, re
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult

D = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(D, "node_modules", "@playwright", "mcp", "cli.js")
PROFILE = os.path.join(D, "profile")
cfg = {"mcpServers": {"pw": {"command": r"C:\Program Files\nodejs\node.exe",
        "args": [CLI, "--browser", "chrome", "--user-data-dir", PROFILE, "--viewport-size", "1280,900", "--image-responses", "omit", "--output-dir", os.path.join(D, "out")]}}}
KEEP = {"browser_navigate", "browser_snapshot", "browser_click", "browser_type", "browser_press_key",
        "browser_select_option", "browser_fill_form", "browser_tabs", "browser_navigate_back", "browser_wait_for", "browser_close"}
KO = {
 "browser_navigate": "웹 브라우저(자동화용 크롬)에서 주소를 연다. 로그인·클릭·입력 등 웹사이트를 직접 조작해야 할 때 쓴다. 단순히 내용만 읽을 땐 crawl_web 이 낫다.",
 "browser_snapshot": "현재 웹페이지의 구조(요소와 ref 번호)를 읽는다. 클릭·입력은 여기 나온 ref 를 쓴다.",
 "browser_click": "웹페이지 요소 클릭. ref=스냅샷의 ref, element=사람이 읽을 요소 설명.",
 "browser_type": "웹페이지 입력칸에 글자 입력. ref, element, text, submit=true 면 엔터.",
 "browser_press_key": "키 누르기 (Enter, Escape, ArrowDown 등).",
 "browser_select_option": "드롭다운에서 항목 선택.",
 "browser_fill_form": "여러 입력칸을 한 번에 채운다.",
 "browser_tabs": "탭 목록·새 탭·탭 전환·탭 닫기.",
 "browser_navigate_back": "뒤로 가기.",
 "browser_wait_for": "글자가 나타나거나 사라질 때까지, 또는 몇 초 기다림.",
 "browser_close": "자동화 브라우저 닫기.",
}
MAXC = 8000

class Trim(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        res = await call_next(context)
        try:
            parts = [b.text for b in res.content if getattr(b, "type", "") == "text"]
            t = "\n".join(parts)
            t = re.sub(r"(?m)^\s*- /url:.*\n?", "", t)
            t = t.replace(" [cursor=pointer]", "")
            t = re.sub(r"(?m)^\s*- generic(?: \[ref=e\d+\])?:\s*\n", "", t)
            t = re.sub(r"(?m)^### Ran Playwright code\n```js\n.*?```\n", "", t, flags=re.S)
            if len(t) > MAXC:
                t = t[:MAXC] + "\n...(페이지 구조가 길어 잘림. 필요한 부분은 browser_wait_for/스크롤 후 다시 browser_snapshot)"
            return ToolResult(content=t)
        except Exception:
            pass
        return res

async def build():
    p = FastMCP.as_proxy(cfg, name="browser")
    tools = await p.list_tools()
    drop = {t.name for t in tools if t.name not in KEEP}
    if hasattr(p, "disable"):
        p.disable(names=drop)
    from fastmcp.tools.tool_transform import ToolTransformConfig
    for n, desc in KO.items():
        try: p.add_tool_transformation(n, ToolTransformConfig(description=desc))
        except Exception as e: print("tt fail", n, e, file=sys.stderr)
    p.add_middleware(Trim())
    return p

if __name__ == "__main__":
    srv = asyncio.run(build())
    srv.run(transport="stdio", show_banner=False)