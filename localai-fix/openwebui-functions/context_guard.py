"""
title: 문맥 한도 가드 (Context Guard)
description: 모델 호출 직전마다 요청 크기를 모델 문맥(num_ctx) 안으로 맞춘다. 오래된 이미지 제거 → 긴 도구 결과 축약 → 가장 오래된 대화 삭제 순.
version: 1.1
"""
import json
from typing import Optional
from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=100, description="다른 필터보다 나중에 실행")
        ctx_map: str = Field(
            default='{"qwen-heretic-262k":262144,"qwen-heretic-64k":65536,"qwen-heretic-32k":32768,"qwen-heretic-16k":16384,"qwen-official":24576,"qwen-uncensored-262k":262144,"qwen-uncensored-64k":65536,"qwen-uncensored-long":32768,"qwen-uncensored":16384}',
            description="모델 ID(앞부분 일치) → num_ctx",
        )
        default_ctx: int = Field(default=16384)
        fill_ratio: float = Field(default=0.80, description="num_ctx 의 이 비율까지만 채움")
        reserve_output: int = Field(default=2048, description="답변용으로 남겨둘 토큰")
        keep_images: int = Field(default=2, description="이미지를 유지할 최근 메시지 수")
        image_tokens: int = Field(default=2600, description="이미지 1장 추정 토큰")
        keep_full_tools: int = Field(default=3, description="원문 유지할 최근 도구 결과 수")
        tool_trim_chars: int = Field(default=1500, description="오래된 도구 결과 축약 길이")

    def __init__(self):
        self.valves = self.Valves()

    # ---------- 추정 ----------
    def _ttok(self, s: str) -> int:
        if not s:
            return 0
        a = sum(1 for ch in s if ord(ch) < 128)
        return int(a / 3.2 + (len(s) - a) * 1.05) + 4

    def _parts(self, m):
        c = m.get("content")
        return c if isinstance(c, list) else None

    def _mtok(self, m) -> int:
        t = 6
        c = m.get("content")
        if isinstance(c, str):
            t += self._ttok(c)
        elif isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") in ("image_url", "input_image", "image"):
                    t += self.valves.image_tokens
                else:
                    t += self._ttok(p.get("text") or "")
        if m.get("tool_calls"):
            t += self._ttok(json.dumps(m["tool_calls"], ensure_ascii=False))
        return t

    def _total(self, body) -> int:
        t = sum(self._mtok(m) for m in body.get("messages", []))
        if body.get("tools"):
            t += self._ttok(json.dumps(body["tools"], ensure_ascii=False))
        return t

    def _ctx(self, body, model) -> int:
        opt = (body.get("options") or {}).get("num_ctx") or body.get("num_ctx")
        if opt:
            return int(opt)
        mid = (body.get("model") or (model or {}).get("id") or "").split(":")[0]
        try:
            mp = json.loads(self.valves.ctx_map)
        except Exception:
            mp = {}
        best = None
        for k, v in mp.items():
            if mid.startswith(k) and (best is None or len(k) > len(best[0])):
                best = (k, v)
        return int(best[1]) if best else self.valves.default_ctx

    # ---------- 줄이기 ----------
    def _short(self, s: str, n: int) -> str:
        if not isinstance(s, str) or len(s) <= n:
            return s
        head = int(n * 0.7)
        return s[:head] + f"\n…(길어서 {len(s) - n}자 생략)…\n" + s[-(n - head):]

    def _drop_old_images(self, msgs):
        idx = [i for i, m in enumerate(msgs) if self._parts(m) and any(isinstance(p, dict) and p.get("type") in ("image_url", "input_image", "image") for p in self._parts(m))]
        for i in idx[:-self.valves.keep_images] if self.valves.keep_images > 0 else idx:
            new = []
            removed = 0
            for p in msgs[i]["content"]:
                if isinstance(p, dict) and p.get("type") in ("image_url", "input_image", "image"):
                    removed += 1
                else:
                    new.append(p)
            new.append({"type": "text", "text": f"[이전 이미지 {removed}장은 문맥 절약을 위해 생략됨]"})
            msgs[i]["content"] = new

    def _trim_tools(self, msgs, keep_full, n):
        tidx = [i for i, m in enumerate(msgs) if m.get("role") == "tool"]
        for i in tidx[:-keep_full] if keep_full > 0 else tidx:
            c = msgs[i].get("content")
            if isinstance(c, str):
                msgs[i]["content"] = self._short(c, n)
            elif isinstance(c, list):
                for p in c:
                    if isinstance(p, dict) and isinstance(p.get("text"), str):
                        p["text"] = self._short(p["text"], n)

    def _drop_oldest(self, msgs):
        # 시스템 메시지와 마지막 사용자 메시지 이후는 보존. 가장 오래된 턴을 통째로 삭제
        sys_n = 0
        while sys_n < len(msgs) and msgs[sys_n].get("role") == "system":
            sys_n += 1
        last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=len(msgs) - 1)
        if last_user <= sys_n:
            return False
        j = sys_n + 1
        while j < last_user and msgs[j].get("role") != "user":
            j += 1
        del msgs[sys_n:j]
        return True

    def _fit(self, body, model):
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs:
            return body
        budget = int(self._ctx(body, model) * self.valves.fill_ratio) - self.valves.reserve_output
        if self._total(body) <= budget:
            return body
        self._drop_old_images(msgs)
        if self._total(body) <= budget:
            return body
        self._trim_tools(msgs, self.valves.keep_full_tools, self.valves.tool_trim_chars)
        if self._total(body) <= budget:
            return body
        self._trim_tools(msgs, 1, 600)
        if self._total(body) <= budget:
            return body
        # 메시지 하나가 예산의 35% 를 넘으면 그 메시지부터 줄인다 (대화를 지우기 전에)
        cap = max(1500, int(budget * 0.35))
        for m in msgs:
            if m.get("role") == "system" or self._mtok(m) <= cap:
                continue
            c = m.get("content")
            if isinstance(c, str):
                m["content"] = self._short(c, cap)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and isinstance(part.get("text"), str) and len(part["text"]) > cap:
                        part["text"] = self._short(part["text"], cap)
        dropped = 0
        while self._total(body) > budget and self._drop_oldest(msgs):
            dropped += 1
        if dropped:
            self._add_system_note(msgs, f"[이전 대화 {dropped}턴은 문맥 한도 때문에 생략됨. 필요하면 사용자에게 다시 물어볼 것]")
        if self._total(body) > budget:
            # 최후: 가장 큰 텍스트부터 줄임
            for _ in range(20):
                big = max(range(len(msgs)), key=lambda k: self._mtok(msgs[k]))
                c = msgs[big].get("content")
                if isinstance(c, str) and len(c) > 800:
                    msgs[big]["content"] = self._short(c, max(800, len(c) // 2))
                elif isinstance(c, list):
                    self._drop_old_images([msgs[big]]) if self.valves.keep_images == 0 else None
                    for p in c:
                        if isinstance(p, dict) and isinstance(p.get("text"), str) and len(p["text"]) > 800:
                            p["text"] = self._short(p["text"], max(800, len(p["text"]) // 2))
                if self._total(body) <= budget:
                    break
        return body


    # ---------- 템플릿 오류 방지 ----------
    def _add_system_note(self, msgs, note):
        # 시스템 메시지를 중간에 끼우면 Qwen 템플릿이 거부할 수 있어서 맨 앞 시스템 메시지에 합친다
        if msgs and msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
            msgs[0]["content"] = (msgs[0]["content"] + "\n\n" + note).strip()
        else:
            msgs.insert(0, {"role": "system", "content": note})

    def _is_query(self, m):
        # Qwen 템플릿 기준 '진짜 사용자 질문': role=user 이고 <tool_response> 로만 된 게 아닌 것
        if m.get("role") != "user":
            return False
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        c = (c or "").strip() if isinstance(c, str) else ""
        return not (c.startswith("<tool_response>") and c.endswith("</tool_response>"))

    def _ensure_user(self, body):
        # 압축·삭제로 사용자 질문이 하나도 안 남으면 Qwen 템플릿이
        # "No user query found in messages" 로 500 을 내고, 그 채팅은 계속 이어지지 않는다 → 이어가기 지시를 넣어 막는다
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs or any(self._is_query(m) for m in msgs):
            return body
        i = 0
        while i < len(msgs) and msgs[i].get("role") == "system":
            i += 1
        msgs.insert(i, {"role": "user", "content": "(앞부분 대화는 문맥 한도 때문에 요약·생략됨. 위 내용과 아래 진행 상황을 바탕으로 하던 작업을 이어서 진행해줘)"})
        return body

    # ---------- 도구 턴 안정화 ----------
    def _tool_turn_tweaks(self, body):
        msgs = body.get("messages") or []
        if not msgs:
            return body
        # 1) 마지막 메시지가 도구 결과면 = 도구 루프 중 → 그 턴만 온도 낮춤 (llama.cpp 토론 권장)
        if msgs[-1].get("role") == "tool":
            body["temperature"] = min(float(body.get("temperature", 0.7) or 0.7), 0.3)
            body.setdefault("min_p", 0.05)
        # 2) 직전 두 번의 도구 호출이 완전히 같으면, 마지막 도구 결과에 경고를 덧붙여 입력을 바꿔준다
        #    (같은 입력 → 같은 출력 고리를 끊기 위함. 3번째는 서버가 강제 중단)
        calls = []
        for m in msgs:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                sig = json.dumps([(t.get("function", {}).get("name"), t.get("function", {}).get("arguments")) for t in m["tool_calls"]], sort_keys=True, ensure_ascii=False)
                calls.append(sig)
        if len(calls) >= 2 and calls[-1] == calls[-2] and msgs[-1].get("role") == "tool":
            note = "\n\n[시스템 경고] 방금 호출은 직전 호출과 완전히 같았고 결과도 같다. 같은 호출을 다시 하면 강제 중단된다. 결과를 이미 받았으니 다음 단계로 넘어가거나, 입력을 바꾸거나, 다른 도구를 쓰거나, 사용자에게 상황을 보고하라."
            c = msgs[-1].get("content")
            if isinstance(c, str):
                msgs[-1]["content"] = c + note
            elif isinstance(c, list):
                c.append({"type": "text", "text": note})
        return body

    def inlet(self, body: dict, __model__: Optional[dict] = None) -> dict:
        try:
            body = self._fit(body, __model__)
        except Exception:
            pass
        try:
            return self._ensure_user(body)
        except Exception:
            return body

    def request(self, body: dict, __model__: Optional[dict] = None) -> dict:
        try:
            body = self._tool_turn_tweaks(body)
            body = self._fit(body, __model__)
        except Exception:
            pass
        try:
            return self._ensure_user(body)
        except Exception:
            return body