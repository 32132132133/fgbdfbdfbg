"""Windows 조작 MCP (CursorTouch Windows-MCP 래퍼) - 로컬 모델용으로 도구를 추리고 보호 폴더 가드를 건다."""
import os, re, json, asyncio
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("MODE", "local")
os.environ.setdefault("PYTHONUTF8", "1")

import windows_mcp.__main__ as wm
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.exceptions import ToolError

# 로컬 27B 모델이 헷갈리지 않게 꼭 필요한 11개만 남긴다 (FileSystem/Scrape 는 다른 MCP와 중복, Screenshot 은 비전 없는 모델엔 무의미)
KEEP = {"App", "PowerShell", "Snapshot", "Click", "Type", "Scroll", "Move", "Shortcut", "Wait", "Clipboard", "Process"}

PROTECTED = [
    r"면준1", r"바탕\s*화면[\\/]+project", r"desktop[\\/]+project",
    r"03_백업자료", r"05_복구사진", r"G:[\\/]+백업",
    r"\.ssh", r"\.gnupg", r"Microsoft[\\/]+Credentials", r"Microsoft[\\/]+Protect",
    r"Login Data", r"key4\.db", r"logins\.json", r"\bcmdkey\b", r"vaultcmd",
]
DANGEROUS = [
    r"format\s+[a-z]:", r"(remove-item|rm|del|rmdir|rd)\b[^\n]*c:[\\/]+windows",
    r"bcdedit", r"diskpart", r"vssadmin\s+delete", r"cipher\s+/w",
    r"Set-MpPreference", r"Disable-WindowsOptionalFeature",
]
_prot = re.compile("|".join(PROTECTED), re.I)
_dang = re.compile("|".join(DANGEROUS), re.I)

class Guard(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        msg = context.message
        blob = " ".join(str(v) for v in (msg.arguments or {}).values())
        # 'local\..\project' 같은 상위 폴더 우회를 풀어서 검사
        prev = None
        while prev != blob:
            prev, blob = blob, re.sub(r"[\\/][^\\/\s'\"]+[\\/]+\.\.(?=[\\/]|$)", "", blob)
        if _prot.search(blob):
            raise ToolError("보호 폴더(면준1, project, 백업, 키/인증 정보)는 사용자가 접근을 막아둔 곳입니다. 이 작업은 할 수 없습니다.")
        if _dang.search(blob):
            raise ToolError("시스템을 망가뜨릴 수 있는 명령이라 차단했습니다. 꼭 필요하면 사용자에게 직접 실행해 달라고 하세요.")
        return await call_next(context)

SHORT = {
 "App": "프로그램 실행·창 전환·창 크기 조정. mode='launch'+name=앱이름(예: 메모장, notepad, chrome) | mode='switch'+name=창제목 | mode='resize'+window_loc/window_size.",
 "PowerShell": "PowerShell 명령을 실행하고 출력을 돌려준다. 파일·폴더·프로그램·시스템 작업은 GUI보다 이걸 먼저 쓴다. timeout=초.",
 "Snapshot": "현재 화면을 읽는다: 현재 창, 다른 창 목록, 요소 목록(번호|종류|이름|값). Click·Type·Shortcut·Scroll·App 은 실행 후 바뀐 화면을 자동으로 같이 돌려주므로, 그 직후에는 Snapshot 을 따로 부를 필요 없다.",
 "Click": "요소 클릭. name=요소 이름(예: '저장', '파일 이름') 또는 label=요소 번호, 둘 다 없으면 loc=[x,y]. button=left|right|middle, clicks=2 는 더블클릭. 실행 후 바뀐 화면이 같이 온다.",
 "Type": "입력칸에 글자 입력. name=입력칸 이름 또는 label=요소 번호(또는 loc=[x,y]). 셋 다 생략하면 지금 커서가 있는 곳(메모장 본문 등)에 입력. text=입력할 글, name 으로 입력칸을 지정하면 기존 내용을 지우고 쓴다(clear=false 로 끌 수 있음). press_enter=true 면 입력 후 엔터. 실행 후 바뀐 화면이 같이 온다.",
 "Scroll": "스크롤. name 또는 label 또는 loc(생략하면 현재 위치), direction=up|down|left|right, wheel_times=횟수.",
 "Move": "마우스 이동. drag=true 면 현재 위치에서 해당 위치까지 드래그.",
 "Shortcut": "단축키 입력. 예: 'ctrl+s', 'ctrl+a', 'alt+tab', 'alt+f4', 'win+d', 'enter', 'esc'.",
 "Wait": "duration 초만큼 대기 (프로그램 로딩 기다릴 때).",
 "Clipboard": "클립보드. mode='get' 읽기 / mode='set'+text 쓰기.",
 "Process": "프로세스. mode='list' 목록(sort_by, limit) / mode='kill'+name 또는 pid 종료.",
}
SNAP_MAX = 6000

def _shorten(s):
    for t in asyncio.run(s.list_tools()):
        if t.name in SHORT:
            try:
                t.description = SHORT[t.name]
                for p in (t.parameters.get("properties") or {}).values():
                    p.pop("description", None)
                if t.name in ("Click", "Type", "Scroll"):
                    t.parameters.setdefault("properties", {})["name"] = {"type": "string"}
            except Exception:
                pass

def _trim_snapshot(text: str) -> str:
    if len(text) <= SNAP_MAX:
        return text
    head, sep, rest = text.partition("List of Interactive Elements:")
    if not sep:
        return text[:SNAP_MAX] + "\n...(화면 정보가 길어 잘림)"
    m = re.search(r"Focused Window:.*?\n-+[^\n]*\n(.+?)\s{2,}\d", head, re.S)
    focus = m.group(1).strip() if m else ""
    lines = rest.split("\n")
    hdr = [l for l in lines[:2]]
    body = lines[2:]
    fl = [l for l in body if focus and ("|" + focus + "|") in l]
    other = [l for l in body if l not in fl]
    out = head + sep + "\n" + "\n".join(hdr) + "\n"
    kept = 0
    for l in fl + other:
        if len(out) + len(l) > SNAP_MAX:
            break
        out += l + "\n"; kept += 1
    dropped = len(fl) + len(other) - kept
    if dropped > 0:
        out += f"...(요소 {dropped}개 생략 — 포커스 창 요소를 우선 표시함. 다른 창을 보려면 App mode='switch' 후 다시 Snapshot)\n"
    return out

class SnapTrim(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        res = await call_next(context)
        if context.message.name == "Snapshot":
            try:
                for blk in res.content:
                    if getattr(blk, "type", "") == "text" and blk.text:
                        t = blk.text
                        try:
                            v = json.loads(t)
                            if isinstance(v, list):
                                t = "\n".join(x for x in v if isinstance(x, str))
                            elif isinstance(v, str):
                                t = v
                        except Exception:
                            pass
                        blk.text = _trim_snapshot(t)
            except Exception:
                pass
        return res

# ---------- 앱 실행 보강: 한글/영문 별칭 → 확실한 실행 + 창 뜰 때까지 대기 ----------
import subprocess, time, ctypes, ctypes.wintypes
APP_ALIASES = {
    "calc.exe": ["계산기", "calculator", "calc"],
    "notepad.exe": ["메모장", "notepad"],
    "mspaint.exe": ["그림판", "paint", "mspaint"],
    "explorer.exe": ["탐색기", "파일 탐색기", "explorer", "file explorer", "내 pc", "내 컴퓨터"],
    "chrome": ["크롬", "chrome", "google chrome"],
    "msedge": ["엣지", "edge", "microsoft edge"],
    "firefox": ["파이어폭스", "firefox"],
    "winword": ["워드", "word", "microsoft word"],
    "excel": ["엑셀", "excel"],
    "powerpnt": ["파워포인트", "powerpoint", "ppt"],
    "wt.exe": ["터미널", "terminal", "windows terminal"],
    "cmd.exe": ["cmd", "명령 프롬프트", "명령프롬프트"],
    "powershell.exe": ["powershell", "파워셸", "파워쉘"],
    "code": ["vscode", "vs code", "visual studio code", "코드"],
    "ms-settings:": ["설정", "settings", "윈도우 설정"],
    "kakaotalk": ["카카오톡", "카톡", "kakaotalk"],
    "discord": ["디스코드", "discord"],
    "taskmgr.exe": ["작업 관리자", "작업관리자", "task manager", "taskmgr"],
    "snippingtool": ["캡처 도구", "캡처", "snipping tool"],
}
_LAUNCHED = {}
_alias_map = {a.lower(): exe for exe, al in APP_ALIASES.items() for a in al}

def _list_windows():
    user32 = ctypes.windll.user32
    out = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h):
            n = user32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1); user32.GetWindowTextW(h, buf, n + 1)
                pid = ctypes.wintypes.DWORD(); user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                out.append((h, buf.value, pid.value))
        return True
    user32.EnumWindows(cb, 0)
    return out

def _launch_alias(name: str):
    key = (name or "").strip().lower()
    exe = _alias_map.get(key)
    if not exe:
        return None
    before = {h for h, _, _ in _list_windows()}
    try:
        if exe.endswith(":"):
            os.startfile(exe)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", exe], creationflags=0x08000000)
    except Exception as e:
        return f"{name} 실행 실패: {e}"
    stem = exe.split(".")[0].rstrip(":").lower()
    stem_alias = {"calc": "calculator", "wt": "windowsterminal", "code": "code", "ms-settings": "systemsettings"}.get(stem, stem)
    def _pname(pid):
        try:
            hp = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not hp: return ""
            buf = ctypes.create_unicode_buffer(1024); n = ctypes.wintypes.DWORD(1024)
            ctypes.windll.kernel32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)); ctypes.windll.kernel32.CloseHandle(hp)
            return os.path.basename(buf.value).lower()
        except Exception:
            return ""
    fallback = None
    for i in range(40):
        time.sleep(0.25)
        new = [(h, t, p) for h, t, p in _list_windows() if h not in before]
        match = [(h, t) for h, t, p in new if stem_alias in _pname(p) or stem in _pname(p)]
        if match:
            h, t = match[0]
        elif new and i >= 12:
            h, t = new[0][0], new[0][1]
        else:
            continue
        if True:
            try:
                ctypes.windll.user32.SetForegroundWindow(h)
            except Exception:
                pass
            _LAUNCHED[(name or "").strip().lower()] = h
            return f"{name} 실행됨. 창 제목: '{t}'. 이 창이 앞에 와 있습니다."
    return f"{name} 실행 명령은 보냈지만 10초 안에 새 창이 안 떴습니다. Snapshot 으로 확인하세요."


def _focus(h):
    u = ctypes.windll.user32
    try:
        if u.IsIconic(h): u.ShowWindow(h, 9)
        fg = u.GetForegroundWindow()
        t1 = u.GetWindowThreadProcessId(fg, None); t2 = ctypes.windll.kernel32.GetCurrentThreadId()
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)
        u.AttachThreadInput(t2, t1, True)
        u.SetForegroundWindow(h); u.BringWindowToTop(h)
        u.AttachThreadInput(t2, t1, False)
    except Exception:
        pass
    return u.GetForegroundWindow() == h

def _switch(name):
    n = (name or "").strip().lower().lstrip("*")
    if not n: return None
    wins = [(h, t) for h, t, p in _list_windows() if t and t.strip()]
    lh = _LAUNCHED.get(n)
    if lh and any(h == lh for h, _ in wins):
        t = next(t for h, t in wins if h == lh)
        ok = _focus(lh)
        return f"'{t}' 창(방금 연 창)으로 전환" + ("함." if ok else " 시도함.")
    for pred in (lambda t: t.lower().lstrip("*").strip() == n, lambda t: n in t.lower()):
        hit = [(h, t) for h, t in wins if pred(t)]
        if hit:
            h, t = hit[0]
            ok = _focus(h)
            return f"'{t}' 창으로 전환" + ("함." if ok else " 시도함(앞으로 안 왔을 수 있음).")
    return "그 이름의 창이 없습니다. 열린 창: " + ", ".join(t for _, t in wins[:15])

def ReadText(window: str = "", max_chars: int = 10000) -> str:
    """지금 화면에 떠 있는 창(또는 window=창 제목 일부)의 '글 내용'을 읽는다. 웹페이지 본문, 문서, 대화창 글처럼 Snapshot 에는 안 나오는 텍스트를 볼 때 쓴다."""
    import uiautomation as auto
    h = ctypes.windll.user32.GetForegroundWindow()
    if window:
        n = window.strip().lower().lstrip("*")
        found = [hh for hh, t, p in _list_windows() if n in t.lower().lstrip("*")]
        if not found:
            return "그 제목의 창이 없습니다. 열린 창: " + ", ".join(t for _, t, _ in _list_windows()[:15])
        h = found[0]
    w = auto.ControlFromHandle(h)
    out = []; t0 = time.time(); cnt = [0]
    KEEPT = ("TextControl", "HyperlinkControl", "HeaderControl", "ListItemControl", "DataItemControl", "DocumentControl")
    def walk(c, d):
        if time.time() - t0 > 10 or cnt[0] > 8000 or d > 70: return
        try: kids = c.GetChildren()
        except Exception: return
        for k in kids:
            cnt[0] += 1
            try:
                if k.ControlTypeName in KEEPT:
                    nm = (k.Name or "").strip()
                    if k.ControlTypeName == "DocumentControl":
                        try:
                            nm = k.GetTextPattern().DocumentRange.GetText(max_chars) or nm
                        except Exception:
                            pass
                    if nm and (not out or out[-1] != nm): out.append(nm)
            except Exception:
                pass
            walk(k, d + 1)
    with auto.UIAutomationInitializerInThread():
        walk(w, 0)
    txt = "\n".join(out)
    if _prot.search(w.Name or ""):
        return "보호된 창이라 읽을 수 없습니다."
    head = f"[창: {w.Name}]\n"
    if len(txt) > max_chars:
        txt = txt[:max_chars] + "\n...(길어서 잘림. 웹페이지면 주소로 docs 의 crawl_web 을 쓰면 전체를 깔끔하게 읽는다)"
    return head + (txt or "(읽을 수 있는 글이 없습니다)")

class AppLaunch(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        msg = context.message
        if msg.name == "App":
            args = msg.arguments or {}
            if args.get("mode") == "switch":
                r = _switch(str(args.get("name") or ""))
                if r is not None:
                    from fastmcp.tools.tool import ToolResult
                    return ToolResult(content=r)
            if (args.get("mode") or "launch") == "launch":
                r = _launch_alias(str(args.get("name") or ""))
                if r is not None:
                    from fastmcp.tools.tool import ToolResult
                    return ToolResult(content=r)
        return await call_next(context)

# ---------- 화면 요약 + 이름으로 클릭 + 동작 후 화면 자동 반환 ----------
_EL = re.compile(r"^(\d+)\|([^|]*)\|([^|]*)\|(.*)\|\((-?\d+),\s*(-?\d+)\)\|(.*)$")
_LAST = {"els": []}

def _parse(text):
    focus = ""
    m = re.search(r"Focused Window:.*?\n-+[^\n]*\n(.+?)\s{2,}\d", text, re.S)
    if m: focus = m.group(1).strip()
    wins = []
    m2 = re.search(r"Opened Windows:.*?\n-+[^\n]*\n(.*?)\n\s*\n", text, re.S)
    if m2:
        for l in m2.group(1).split("\n"):
            n = re.split(r"\s{2,}", l.strip())[0] if l.strip() else ""
            if n: wins.append(n)
    els = []
    for l in text.split("\n"):
        mm = _EL.match(l.strip())
        if mm:
            i, w, ct, nm, x, y, meta = mm.groups()
            val = ""
            try:
                md = json.loads(meta)
                if md.get("value") and md.get("value") != "(empty)": val = str(md["value"])[:60]
                if md.get("toggle_state"): val = "상태:" + md["toggle_state"]
            except Exception:
                pass
            if int(x) <= 0 and int(y) <= 0:
                continue
            els.append({"id": int(i), "win": w, "type": ct, "name": nm, "x": int(x), "y": int(y), "val": val})
    return focus, wins, els

def _compact(text, limit=70):
    focus, wins, els = _parse(text)
    if not els and not focus:
        return _trim_snapshot(text)
    _LAST["els"] = els
    try:
        open(r"C:\Users\gu214\LocalAI\bench\last_els.json", "w", encoding="utf-8").write(json.dumps(els, ensure_ascii=False))
    except Exception:
        pass
    fe = [e for e in els if e["win"] == focus] or els
    from collections import Counter
    cnt = Counter((e["type"], e["name"]) for e in fe)
    seen = Counter(); fe2 = []
    for e in fe:
        k = (e["type"], e["name"]); seen[k] += 1
        if cnt[k] > 3 and seen[k] > 1:
            continue
        fe2.append(e)
    PRI = {"편집": 0, "콤보 상자": 1, "단추": 2, "분할 단추": 2, "메뉴 항목": 3, "탭 항목": 3, "확인란": 3, "라디오 단추": 3, "링크": 4, "하이퍼링크": 4}
    fe = sorted(fe2, key=lambda e: PRI.get(e["type"], 5))
    oe = [e for e in els if e not in fe]
    out = [f"현재 창: {focus or '(없음)'}"]
    others = [w for w in wins if w != focus]
    if others: out.append("다른 창: " + ", ".join(others[:12]))
    out.append("요소 (번호|종류|이름|값) — Click/Type 에 label=번호 또는 name=이름:")
    oe = oe[:15]
    for e in (fe + oe)[:limit]:
        tag = "" if e["win"] == focus else f"[{e['win']}] "
        out.append(f"{e['id']}|{e['type']}|{tag}{e['name']}" + (f"|{e['val']}" if e["val"] else ""))
    if len(fe + oe) > limit:
        out.append(f"...(요소 {len(fe + oe) - limit}개 더 있음. 필요하면 Scroll 하거나 창을 전환한 뒤 Snapshot)")
    return "\n".join(out)

def _find(name, edit=False):
    n = (name or "").strip().lower().rstrip(":")
    if not n: return None
    els = _LAST["els"]
    for pred in (lambda e: e["name"].strip().lower() == n,
                 lambda e: e["name"].strip().lower().startswith(n),
                 lambda e: n in e["name"].strip().lower()):
        hit = [e for e in els if pred(e)]
        if hit:
            if edit:
                hit.sort(key=lambda e: 0 if e["type"] in ("편집", "Edit", "문서", "Document") else 1)
            return hit[0]
    return None

def _text_of(res):
    parts = []
    for blk in getattr(res, "content", []) or []:
        if getattr(blk, "type", "") == "text" and blk.text:
            t = blk.text
            try:
                v = json.loads(t)
                if isinstance(v, list): t = "\n".join(x for x in v if isinstance(x, str))
                elif isinstance(v, str): t = v
            except Exception:
                pass
            parts.append(t)
    return "\n".join(parts)

SERVER = {"s": None}
AFTER = {"Click", "Type", "Shortcut", "Scroll", "App"}

_HIST = []
REPEAT_NOTE = ("\n\n[주의] 방금과 똑같은 동작을 또 했습니다. 같은 호출을 반복해도 결과는 같습니다. "
               "위 화면을 보고 목표가 이미 이뤄졌으면 바로 사용자에게 답하고, 아니면 방법을 바꾸세요 "
               "(예: 사이트 열기는 PowerShell 로 Start-Process 'https://주소' — 네이버 검색은 https://search.naver.com/search.naver?query=검색어, "
               "화면 글 확인은 ReadText, 요소는 다른 이름·번호로).")

class SmartUI(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        from fastmcp.tools.tool import ToolResult as _TR
        msg = context.message
        try:
            sig = msg.name + json.dumps(msg.arguments or {}, sort_keys=True, ensure_ascii=False)
        except Exception:
            sig = msg.name
        rep = msg.name not in ("Snapshot", "Wait", "ReadText") and bool(_HIST) and _HIST[-1] == sig
        rep3 = rep and len(_HIST) >= 2 and _HIST[-2] == sig
        _HIST.append(sig); del _HIST[:-5]
        if rep3:
            t = ("[실행 안 함] 똑같은 동작을 세 번째 하려고 해서 막았습니다. 이 방법은 안 통합니다. 반드시 다른 방법을 쓰세요: "
                 "사이트는 PowerShell 로 Start-Process 'https://주소'(네이버 검색 https://search.naver.com/search.naver?query=검색어), "
                 "화면 글 읽기는 ReadText, 파일 작업은 PowerShell. 이미 목표를 이뤘다면 사용자에게 결과를 답하세요.")
            return _TR(content=t, structured_content={"result": t})
        res = await self._inner(context, call_next)
        if rep:
            t = _text_of(res) + REPEAT_NOTE
            return _TR(content=t, structured_content={"result": t})
        return res

    async def _inner(self, context: MiddlewareContext, call_next):
        msg0 = context.message
        if msg0.name in ("Type", "Shortcut", "Click", "Scroll"):
            try:
                fg = ctypes.windll.user32.GetForegroundWindow()
                n = ctypes.windll.user32.GetWindowTextLengthW(fg); buf = ctypes.create_unicode_buffer(n + 1)
                ctypes.windll.user32.GetWindowTextW(fg, buf, n + 1); title = buf.value
            except Exception:
                title = ""
            a0 = msg0.arguments or {}
            untargeted = a0.get("label") is None and not a0.get("loc") and not a0.get("name")
            if (title == "Claude" or "Open WebUI" in title) and (untargeted or msg0.name == "Shortcut"):
                from fastmcp.tools.tool import ToolResult as _TR2
                t = (f"지금 맨 앞 창이 '{title}'(사용자가 보고 있는 채팅 창)이라 입력·단축키를 보내지 않았습니다. "
                     "작업할 창으로 먼저 전환하세요: open_app(name='창 이름', switch=true).")
                return _TR2(content=t, structured_content={"result": t})
        from fastmcp.tools.tool import ToolResult as _TR
        def ToolResult(content):
            return _TR(content=content, structured_content={"result": content})
        msg = context.message
        args = dict(msg.arguments or {})
        if msg.name in ("Click", "Type", "Scroll") and args.get("name") and args.get("label") is None and not args.get("loc"):
            e = _find(args.pop("name"), edit=(msg.name == "Type"))
            if not e:
                return ToolResult(content="그 이름의 요소를 최근 화면에서 못 찾았습니다. Snapshot 을 다시 보고 정확한 이름이나 번호(label)를 쓰세요.")
            if e["x"] <= 0 and e["y"] <= 0:
                return ToolResult(content=f"'{e['name']}' 요소는 위치를 알 수 없습니다. 같은 이름의 다른 요소 번호(label)를 쓰거나 Snapshot 을 다시 보세요.")
            args["label"] = e["id"]
            if msg.name == "Type" and "clear" not in args and e["type"] in ("편집", "Edit", "콤보 상자"):
                args["clear"] = True
            msg.arguments = args
        elif "name" in args and msg.name in ("Click", "Type", "Scroll"):
            args.pop("name"); msg.arguments = args
        if msg.name == "Type" and args.get("label") is None and not args.get("loc") and SERVER["s"] is not None:
            txt = str(args.get("text") or "")
            srv = SERVER["s"]
            if args.get("clear"):
                await srv.call_tool("Shortcut", {"shortcut": "ctrl+a"}, run_middleware=False)
            await srv.call_tool("Clipboard", {"mode": "set", "text": txt}, run_middleware=False)
            await srv.call_tool("Shortcut", {"shortcut": "ctrl+v"}, run_middleware=False)
            if args.get("press_enter"):
                await asyncio.sleep(0.2)
                await srv.call_tool("Shortcut", {"shortcut": "enter"}, run_middleware=False)
            await asyncio.sleep(0.8)
            snap = await srv.call_tool("Snapshot", {}, run_middleware=False)
            return ToolResult(content=f"현재 포커스된 곳에 입력함: {txt[:80]}\n\n[동작 후 화면]\n" + _compact(_text_of(snap), limit=45))
        if msg.name == "Snapshot":
            res = await call_next(context)
            return ToolResult(content=_compact(_text_of(res)))
        res = await call_next(context)
        if msg.name in AFTER and SERVER["s"] is not None:
            try:
                await asyncio.sleep(1.3 if msg.name in ("Shortcut", "App") else 0.8)
                snap = await SERVER["s"].call_tool("Snapshot", {}, run_middleware=False)
                view = _compact(_text_of(snap), limit=45)
                return ToolResult(content=_text_of(res) + "\n\n[동작 후 화면]\n" + view)
            except Exception as ex:
                return ToolResult(content=_text_of(res) + f"\n(화면 자동 확인 실패: {ex})")
        return res

async def _prune(s):
    drop = {t.name for t in await s.list_tools() if t.name not in KEEP}
    if hasattr(s, "disable"):
        s.disable(names=drop)
    else:
        for n in drop:
            s.remove_tool(n)

if __name__ == "__main__":
    server = wm._build_local_mcp()
    asyncio.run(_prune(server))
    server.tool(ReadText)
    _shorten(server)
    server.add_middleware(Guard())
    server.add_middleware(SmartUI())
    server.add_middleware(AppLaunch())
    SERVER['s'] = server
    server.run(transport="stdio", show_banner=False)