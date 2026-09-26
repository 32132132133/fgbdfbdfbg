"""
title: 자동 대화 요약 (Auto Context Summary)
author: local
version: 1.1
description: 대화가 모델 컨텍스트 한도에 가까워지면 오래된 메시지를 같은 로컬 모델로 요약해 넣고 최근 대화만 원문으로 보냅니다. 요약은 채팅별로 저장되어 누적 갱신됩니다.
"""
import json, os, re, time
from typing import Optional, Callable, Any
import httpx
from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        ollama_url: str = Field(default="http://127.0.0.1:11434")
        ctx_map: str = Field(
            default='{"262k": 262144, "64k": 65536, "32k": 32768, "16k": 16384, "official": 24576, "long": 32768, "default": 16384}',
            description="모델 id에 포함된 키워드 → 컨텍스트 길이 (앞에서부터 먼저 맞는 것)",
        )
        overhead_tokens: int = Field(default=4000, description="시스템 프롬프트·도구 정의·답변 여유분")
        trigger_ratio: float = Field(default=0.75, description="예산의 이 비율을 넘으면 요약")
        keep_recent_ratio: float = Field(default=0.35, description="원문으로 남길 최근 대화 비율")
        tokens_per_char: float = Field(default=1.05, description="한글 1글자당 토큰 추정치 (영문·숫자는 3.2글자=1토큰으로 따로 계산)")
        summary_max_tokens: int = Field(default=900)
        priority: int = Field(default=0)

    def __init__(self):
        self.valves = self.Valves()
        base = os.environ.get("DATA_DIR", os.path.expanduser("~/LocalAI/webui-data"))
        self.store = os.path.join(base, "summaries")
        os.makedirs(self.store, exist_ok=True)

    # ---------- helpers ----------
    def _text(self, m) -> str:
        c = m.get("content", "")
        if isinstance(c, list):
            c = "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        s = str(c or "")
        if m.get("tool_calls"):
            s += "\n[도구 호출] " + json.dumps(m["tool_calls"], ensure_ascii=False)[:500]
        return s

    def _tok(self, msgs) -> int:
        t = 0
        for m in msgs:
            s = self._text(m)
            a = sum(1 for ch in s if ord(ch) < 128)
            t += int(a / 3.2 + (len(s) - a) * self.valves.tokens_per_char) + 8
        return t

    def _ctx(self, model_id: str) -> int:
        try:
            mp = json.loads(self.valves.ctx_map)
        except Exception:
            mp = {"default": 12288}
        for k, v in mp.items():
            if k != "default" and k in (model_id or ""):
                return int(v)
        return int(mp.get("default", 12288))

    def _load(self, chat_id):
        p = os.path.join(self.store, re.sub(r"[^\w\-]", "_", chat_id) + ".json")
        try:
            with open(p, encoding="utf-8") as f:
                return p, json.load(f)
        except Exception:
            return p, {"upto": 0, "summary": ""}

    async def _status(self, emit, text, done=False):
        if emit:
            try:
                await emit({"type": "status", "data": {"description": text, "done": done, "hidden": done}})
            except Exception:
                pass

    async def _summarize(self, model, prev, msgs) -> str:
        convo = "\n".join(f"{m.get('role')}: {self._text(m)}" for m in msgs)
        prompt = (
            "다음은 사용자와 AI의 이전 대화입니다. 이후 대화를 이어가는 데 필요한 정보만 한국어로 압축 요약하세요.\n"
            "- 사용자의 목표, 요청사항, 선호, 결정된 사항, 중요한 사실·수치·파일명·코드 요지, 아직 해결 안 된 일을 빠짐없이.\n"
            "- 불필요한 인사·반복은 제거. 글머리표 목록으로. 최대 약 600단어.\n\n"
            + (f"[기존 요약]\n{prev}\n\n" if prev else "")
            + f"[새로 요약할 대화]\n{convo}\n\n[갱신된 전체 요약]"
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"num_predict": self.valves.summary_max_tokens, "temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(self.valves.ollama_url.rstrip("/") + "/api/chat", json=payload)
            r.raise_for_status()
            return (r.json().get("message", {}) or {}).get("content", "").strip()

    # ---------- main ----------
    async def inlet(self, body: dict, __event_emitter__: Optional[Callable[[Any], Any]] = None,
                    __chat_id__: Optional[str] = None, __metadata__: Optional[dict] = None) -> dict:
        msgs = body.get("messages") or []
        chat_id = __chat_id__ or (__metadata__ or {}).get("chat_id")
        if not msgs or not chat_id or str(chat_id).startswith("local:"):
            return body
        model = body.get("model", "")
        budget = max(2000, self._ctx(model) - self.valves.overhead_tokens)

        sys_msgs = [m for m in msgs if m.get("role") == "system"]
        conv = [m for m in msgs if m.get("role") != "system"]
        path, st = self._load(chat_id)
        upto = int(st.get("upto", 0))
        summary = st.get("summary", "")
        if upto > len(conv):  # 대화가 편집/재생성되어 짧아진 경우 초기화
            upto, summary = 0, ""

        def build(u, s):
            # 시스템 메시지는 하나로 합쳐 맨 앞에만 둔다 (Qwen 템플릿은 중간 system 을 거부할 수 있음)
            texts = [m.get("content") for m in sys_msgs if isinstance(m.get("content"), str) and m.get("content").strip()]
            if s:
                texts.append("[이전 대화 요약 — 오래된 대화는 아래 요약으로 대체됨]\n" + s)
            others = [m for m in sys_msgs if not isinstance(m.get("content"), str)]
            out = ([{"role": "system", "content": "\n\n".join(texts)}] if texts else []) + others
            out.extend(conv[u:])
            return out

        cur = build(upto, summary)
        if self._tok(cur) > budget * self.valves.trigger_ratio:
            keep_budget = budget * self.valves.keep_recent_ratio
            # 최근 메시지를 뒤에서부터 keep_budget만큼 남김 (최소 2개)
            cut, acc = len(conv), 0
            while cut > upto and (len(conv) - cut < 2 or acc + self._tok([conv[cut - 1]]) <= keep_budget):
                acc += self._tok([conv[cut - 1]])
                cut -= 1
            # 경계는 user 메시지에서 시작하도록 조정. 뒤에 user 가 없으면(도구 연속 호출 중)
            # 마지막 user 부터 남긴다 — 질문까지 요약해 버리면 템플릿이 "No user query" 로 실패함
            nxt = next((i for i in range(cut, len(conv)) if conv[i].get("role") == "user"), None)
            if nxt is None:
                nxt = max((i for i in range(len(conv)) if conv[i].get("role") == "user"), default=upto)
            cut = nxt
            if cut > upto:
                await self._status(__event_emitter__, "이전 대화 요약 중...")
                try:
                    t0 = time.time()
                    new = await self._summarize(model, summary, conv[upto:cut])
                    if new:
                        summary, upto = new, cut
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump({"upto": upto, "summary": summary, "updated": time.time()}, f, ensure_ascii=False)
                    await self._status(__event_emitter__, f"이전 대화 요약 완료 ({time.time()-t0:.0f}초)", done=True)
                except Exception as e:
                    await self._status(__event_emitter__, f"요약 실패: {e}", done=True)
            cur = build(upto, summary)

        body["messages"] = cur
        return body