"""도구 게이트웨이: 자주 쓰는 핵심 도구만 모델에 보여주고, 나머지는 tool_search → tool_call 로 필요할 때 꺼내 쓴다.
(도구 설명 입력 토큰을 1/4 로 줄이기 위함. 실제 실행은 mcpo 의 각 서버로 전달)"""
import json, os, re, time, httpx
from fastmcp import FastMCP

M = "http://127.0.0.1:8765"
mcp = FastMCP("tools")
# mcpo 에 인증키가 걸려 있으면 같은 키로 부른다 (LocalAI\.mcpo_key)
_KEYF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".mcpo_key")
_KEY = open(_KEYF, encoding="utf-8").read().strip() if os.path.exists(_KEYF) else ""
H = httpx.Client(timeout=900, headers={"Authorization": f"Bearer {_KEY}"} if _KEY else {})

def _call(srv, tool, args):
    args = {k: v for k, v in (args or {}).items() if v is not None and v != ""}
    try:
        r = H.post(f"{M}/{srv}/{tool}", json=args)
    except Exception as e:
        return f"도구 호출 실패({srv}/{tool}): {e}"
    try:
        v = r.json()
    except Exception:
        return r.text
    if r.status_code >= 400:
        return f"오류: {json.dumps(v, ensure_ascii=False)[:800]}"
    if isinstance(v, str): return v
    if isinstance(v, dict) and set(v) == {"result"}: v = v["result"]
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

# ---------------- 핵심 도구 (항상 보임) ----------------
@mcp.tool
def web_search(query: str, category: str = "general", time_range: str = "", max_results: int = 8) -> str:
    """인터넷 검색(구글·빙·네이버 통합). category: general|news|images|videos. time_range: day|week|month|year."""
    return _call("search", "web_search", dict(query=query, category=category, time_range=time_range, max_results=max_results))

@mcp.tool
def read_web(url: str, keyword: str = "", max_pages: int = 1) -> str:
    """웹페이지 본문을 깔끔한 글로 읽기(자바스크립트 페이지도 됨). keyword 주면 그 부분만, max_pages>1 이면 사이트 안 여러 페이지."""
    return _call("docs", "crawl_web", dict(url=url, keyword=keyword, max_pages=max_pages))

@mcp.tool
def read_document(path: str, ocr: bool = False) -> str:
    """파일 내용 읽기: PDF·워드·엑셀·PPT·한글HWP·이미지(글자인식)·유튜브 자막. path=경로 또는 URL."""
    if path.strip().strip('"').lower().endswith((".hwp", ".hwpx", ".hwpml")):
        r = _call("kordoc", "parse_document", dict(file_path=path.strip().strip('"')))
        if r and not r.startswith("오류") and not r.startswith("도구 호출 실패"):
            return r
    return _call("docs", "read_document", dict(path=path, ocr=ocr))

@mcp.tool
def spell_check(text: str) -> str:
    """한국어 맞춤법·띄어쓰기 검사(네이버 맞춤법 검사기). 고친 문장을 돌려준다. 자기소개서·보고서·메일 다듬을 때."""
    parts, cur = [], ""
    for line in (text or "").splitlines(True):
        if len(cur) + len(line) > 480 and cur:
            parts.append(cur); cur = ""
        cur += line
    if cur: parts.append(cur)
    return "".join(_call("spell", "fix_korean_spell", {"text": p}).strip('"') for p in parts)

@mcp.tool
def find_files(query: str, search_content: bool = False, folder: str = "") -> str:
    """파일 찾기. 기본은 컴퓨터 전체 파일 이름 검색(예: 'ext:pdf 보고서'). search_content=true 면 folder 안 파일 내용 검색."""
    return _call("docs", "find_files", dict(query=query, search_content=search_content, folder=folder))

@mcp.tool
def powershell(command: str, timeout: int = 60) -> str:
    """PowerShell 명령 실행. 파일·폴더·프로그램·시스템·사이트 열기(Start-Process 'https://...') 등은 이걸로."""
    return _call("desktop", "PowerShell", dict(command=command, timeout=timeout))

@mcp.tool
def open_app(name: str, switch: bool = False) -> str:
    """프로그램 실행(한글 이름 가능: 메모장, 계산기, 크롬…). switch=true 면 이미 열린 창(제목 일부)으로 전환. 실행 후 화면이 같이 온다."""
    return _call("desktop", "App", dict(mode="switch" if switch else "launch", name=name))

@mcp.tool
def click(name: str = "", label: int = None, double: bool = False, right: bool = False) -> str:
    """화면 요소 클릭. name=요소 이름(예 '저장') 또는 label=화면 목록의 번호. 클릭 후 바뀐 화면이 같이 온다."""
    a = dict(name=name, label=label, clicks=2 if double else 1, button="right" if right else "left")
    return _call("desktop", "Click", a)

@mcp.tool
def type_text(text: str, name: str = "", label: int = None, enter: bool = False) -> str:
    """글자 입력. name=입력칸 이름 또는 label=번호(기존 내용 지우고 씀). 둘 다 없으면 지금 커서 위치에. enter=true 면 입력 후 엔터."""
    return _call("desktop", "Type", dict(text=text, name=name, label=label, press_enter=enter))

@mcp.tool
def press_keys(keys: str) -> str:
    """단축키/키 입력. 예 'ctrl+s', 'enter', 'esc', 'alt+tab', 'ctrl+a'. 누른 뒤 화면이 같이 온다."""
    return _call("desktop", "Shortcut", dict(shortcut=keys))

@mcp.tool
def see_screen(text: bool = False, window: str = "") -> str:
    """지금 화면 보기. 기본은 창·버튼·입력칸 목록(번호·이름). text=true 면 창 안의 글 내용(웹페이지 본문, 문서)을 읽는다."""
    if text:
        return _call("desktop", "ReadText", dict(window=window))
    return _call("desktop", "Snapshot", {})

# ---------------- 추가 도구 (검색해서 꺼내 씀) ----------------
EXTRA = {
    "desktop": ({"Scroll", "Move", "Wait", "Clipboard", "Process"}, "화면 스크롤 마우스 드래그 대기 클립보드 복사 붙여넣기 프로세스 종료 작업관리자"),
    "docs": ({"transcribe", "download_media"}, "받아쓰기 음성 녹음 영상 자막 유튜브 다운로드 음악 받기"),
    "browser": (None, "브라우저 자동화 웹사이트 조작 로그인 클릭 입력 폼 작성 탭 playwright"),
    "filesystem": (None, "파일 폴더 읽기 쓰기 만들기 수정 편집 이동 이름변경 목록 트리 검색 정보"),
    "memory": (None, "기억 지식그래프 사람 관계 엔티티 저장 메모 관찰"),
    "time": (None, "시간 시간대 변환 현재시각 세계시간"),
    "kordoc": (None, "한글 hwp hwpx 공문서 양식 서식 채우기 작성 표 추출 문서 비교 도장 날인 공문 보고서 생성 개인정보 가리기"),
    "fetch": (None, "웹페이지 원문 가져오기 fetch url html"),
}
_CAT = {}
KO = {
 "read_text_file": "파일 읽기 텍스트 내용", "read_multiple_files": "여러 파일 읽기", "write_file": "파일 쓰기 저장 만들기 새로",
 "edit_file": "파일 수정 편집 바꾸기 고치기", "create_directory": "폴더 만들기 생성", "list_directory": "폴더 목록 보기",
 "list_directory_with_sizes": "폴더 목록 크기 용량", "directory_tree": "폴더 구조 트리", "move_file": "파일 이동 이름변경 옮기기 바꾸기",
 "search_files": "파일 검색 찾기", "get_file_info": "파일 정보 크기 날짜", "list_allowed_directories": "허용 폴더",
 "read_media_file": "이미지 사진 오디오 파일 보기",
 "create_entities": "기억 저장 사람 사물 추가", "create_relations": "관계 저장", "add_observations": "기억 사실 추가",
 "search_nodes": "기억 검색 찾기", "read_graph": "기억 전체 보기", "open_nodes": "기억 열기", "delete_entities": "기억 삭제",
 "browser_navigate": "사이트 열기 주소 이동", "browser_snapshot": "페이지 구조 요소 ref 보기", "browser_click": "웹 클릭 버튼 누르기",
 "browser_type": "웹 입력 글자 쓰기 검색창", "browser_fill_form": "폼 여러칸 채우기 회원 신청서", "browser_tabs": "탭 새탭 전환 닫기",
 "browser_close": "브라우저 닫기", "browser_press_key": "웹 키 누르기 엔터", "browser_select_option": "드롭다운 선택",
 "browser_wait_for": "웹 기다리기 로딩", "browser_navigate_back": "뒤로가기",
 "Scroll": "스크롤 내리기 올리기", "Move": "마우스 이동 드래그 끌기", "Wait": "대기 기다리기", "Clipboard": "클립보드 복사 붙여넣기",
 "Process": "프로세스 목록 종료 강제종료 작업관리자", "get_current_time": "현재 시간 시각", "convert_time": "시간대 변환",
 "fetch": "웹페이지 원문 html",
 "parse_document": "한글 hwp 문서 읽기 마크다운", "parse_table": "표 읽기", "extract_tables": "표 추출 엑셀",
 "parse_form": "양식 빈칸 서식 항목 확인", "fill_form": "양식 채우기 서식 작성 지원서 입력", "patch_document": "한글 문서 수정 내용 바꾸기",
 "generate_document": "한글 hwp 공문 보고서 새로 만들기 작성 생성", "compare_documents": "문서 비교 차이", "place_seal": "도장 날인 서명",
 "redact_document": "개인정보 가리기 마스킹", "render_document": "문서 이미지 미리보기",
}

def _load():
    if _CAT: return
    for srv, (only, tags) in EXTRA.items():
        try:
            sp = H.get(f"{M}/{srv}/openapi.json", timeout=15).json()
        except Exception:
            continue
        comps = sp.get("components", {}).get("schemas", {})
        def res(o):
            if isinstance(o, dict):
                if "$ref" in o: return res(comps.get(o["$ref"].split("/")[-1], {}))
                return {k: res(v) for k, v in o.items()}
            if isinstance(o, list): return [res(x) for x in o]
            return o
        for p, ops in sp.get("paths", {}).items():
            name = p.strip("/")
            if only and name not in only: continue
            op = ops.get("post", {})
            sch = res(op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}))
            props = sch.get("properties", {}) or {}
            req = set(sch.get("required", []) or [])
            ps = []
            for k, v in props.items():
                t = v.get("type") or ("/".join(x.get("type", "?") for x in v.get("anyOf", []) if isinstance(x, dict)) or "any")
                ps.append(f"{k}{'' if k in req else '?'}:{t}")
            desc = re.sub(r"\s+", " ", (op.get("description") or op.get("summary") or "")).strip()[:220]
            _CAT[f"{srv}.{name}"] = {"srv": srv, "tool": name, "desc": desc, "params": ", ".join(ps), "tags": tags, "ko": KO.get(name, "")}

@mcp.tool
def tool_search(query: str = "") -> str:
    """위 도구로 안 되는 일(파일 직접 편집·이동, 받아쓰기, 영상 다운로드, 브라우저 로그인·폼 자동화, 스크롤, 클립보드, 프로세스 종료, 지식그래프 기억, 시간대 변환 등)에 쓸 추가 도구를 찾는다. 결과의 이름으로 tool_call 한다."""
    _load()
    q = [w for w in re.split(r"[\s,]+", (query or "").lower()) if w]
    scored = []
    for k, v in _CAT.items():
        hay = (k + " " + v["desc"] + " " + v["tags"]).lower()
        s = sum(3 if w in v["ko"] else (2 if w in k.lower() else (1 if w in hay else 0)) for w in q) if q else 1
        if s: scored.append((s, k))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "맞는 도구가 없습니다. 전체 목록: " + ", ".join(_CAT)
    out = [f"{k}({_CAT[k]['params']}) — {(_CAT[k]['ko'] + ' | ') if _CAT[k]['ko'] else ''}{_CAT[k]['desc'][:140]}" for _, k in scored[:6]]
    return "\n".join(out) + "\n\n사용법: tool_call(name='위 이름', arguments={...})"

@mcp.tool
def tool_call(name: str, arguments: dict | str = {}) -> str:
    """tool_search 로 찾은 추가 도구 실행. name='서버.도구', arguments=매개변수 객체."""
    _load()
    v = _CAT.get(name) or next((x for k, x in _CAT.items() if k.endswith("." + name) or k.lower() == name.lower()), None)
    if not v:
        return f"'{name}' 도구가 없습니다. tool_search 로 먼저 찾으세요."
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            try:
                from json_repair import repair_json
                arguments = json.loads(repair_json(arguments))
            except Exception:
                return "arguments 는 JSON 객체여야 합니다."
    if not isinstance(arguments, dict):
        return "arguments 는 {이름: 값} 형태의 객체여야 합니다."
    types = {}
    for p in v["params"].split(", "):
        if ":" in p:
            k, t = p.split(":", 1)
            types[k.rstrip("?")] = t
    fixed = {}
    for k, val in arguments.items():
        t = types.get(k, "")
        if isinstance(val, str):
            low = val.strip().lower()
            if "boolean" in t and low in ("true", "false"):
                val = low == "true"
            elif ("integer" in t or "number" in t) and re.fullmatch(r"-?\d+(\.\d+)?", low):
                val = float(low) if ("." in low and "number" in t) else int(float(low))
            elif ("object" in t or "array" in t) and low[:1] in "[{":
                try:
                    val = json.loads(val)
                except Exception:
                    try:
                        from json_repair import repair_json
                        val = json.loads(repair_json(val))
                    except Exception:
                        pass
        fixed[k] = val
    return _call(v["srv"], v["tool"], fixed)

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)