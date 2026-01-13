import os
import json
import re
import time
from typing import List, Dict, Any, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ----------------------------
# Config
# ----------------------------
load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()
# auto: zhipu -> gemini -> stub
# zhipu: force zhipu (fail -> error)
# gemini: force gemini (fail -> error)
# stub: force stub

# Zhipu (BigModel) OpenAI-compatible endpoint
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "").strip()
ZHIPU_MODEL = os.getenv("ZHIPU_MODEL", "glm-4.5-air").strip()
ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn").rstrip("/")
ZHIPU_CHAT_PATH = "/api/paas/v4/chat/completions"

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("gemini_api_key", "")).strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# General
REQ_TIMEOUT = float(os.getenv("REQ_TIMEOUT", "40"))
DEBUG = os.getenv("DEBUG", "0").strip().lower() in ("1", "true", "yes")

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI(title="Research IDE Prototype Backend", version="1.0.0")

# CORS (demo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Serve Frontend (index.html + static folders)
# ----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(BASE_DIR, "index.html")

@app.get("/")
def serve_index():
    if os.path.exists(INDEX_HTML):
        return FileResponse(INDEX_HTML)
    raise HTTPException(status_code=404, detail="index.html not found in project directory")

# If you have assets/static/public folders, auto-mount them
for folder in ["assets", "static", "public"]:
    path = os.path.join(BASE_DIR, folder)
    if os.path.isdir(path):
        app.mount(f"/{folder}", StaticFiles(directory=path), name=folder)

# ----------------------------
# Request / Response Models
# ----------------------------
class SynthesisReq(BaseModel):
    topic: str
    selectedIds: List[int] = []

# ----------------------------
# Helpers: JSON extraction
# ----------------------------
def _extract_json_array(text: str) -> str:
    if not text:
        return "[]"
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
    m = re.search(r"\[\s*\{.*\}\s*\]", text, flags=re.DOTALL)
    if m:
        return m.group(0)
    i, j = text.find("["), text.rfind("]")
    if i != -1 and j != -1 and j > i:
        return text[i : j + 1]
    return "[]"

def _safe_json_loads(s: str, default):
    try:
        return json.loads(s)
    except Exception:
        return default

# ----------------------------
# Providers
# ----------------------------
def _call_zhipu(prompt: str) -> str:
    if not ZHIPU_API_KEY:
        raise RuntimeError("Missing ZHIPU_API_KEY")

    url = f"{ZHIPU_BASE_URL}{ZHIPU_CHAT_PATH}"
    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ZHIPU_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个学术检索与选题助手。输出必须严格按要求格式。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.6,
    }

    if DEBUG:
        print(f">>> [zhipu] calling model={ZHIPU_MODEL} url={url}")

    r = requests.post(url, headers=headers, json=payload, timeout=REQ_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"Zhipu error {r.status_code}: {r.text[:400]}")

    data = r.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Zhipu response parse failed: {str(data)[:400]}")

def _call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Missing GEMINI_API_KEY")

    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.6},
    }

    if DEBUG:
        print(f">>> [gemini] calling model={GEMINI_MODEL}")

    r = requests.post(GEMINI_ENDPOINT, params=params, json=payload, timeout=REQ_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:400]}")
    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini response parse failed: {str(data)[:400]}")

# ----------------------------
# Stub (fallback)
# ----------------------------
def _stub_candidates(topic: str) -> List[Dict[str, Any]]:
    base = [
        ("算法治理与劳动主体性异化：平台经济下的工人困境研究", 2022, "批判理论 / 劳动哲学", "案例研究 / 理论阐释"),
        ("可信AI的构建路径：从技术规制到社会协同治理的多元面向", 2023, "治理理论 / 技术哲学", "比较研究 / 政策分析"),
        ("生成式AI对人类创造力重塑的伦理审思：认知协作与主体能动性的平衡", 2024, "教育哲学 / 认知科学", "理论阐释 / 概念分析"),
        ("算法偏见与社会公平：基于大模型训练数据的批判性考察", 2021, "社会哲学 / 数据伦理", "文本分析 / 批判性分析"),
        ("自动驾驶伦理困境的哲学探析：责任分配与道德算法的限度", 2020, "伦理学 / 实践哲学", "思想实验 / 规范伦理学分析"),
        ("数字永生与主体认同：人工智能时代个体记忆的储存与传承", 2025, "存在主义哲学 / 主体性研究", "哲学思辨 / 未来学研究"),
    ]
    out = []
    for i, (title, year, angle, method) in enumerate(base, start=1):
        out.append(
            {
                "id": i,
                "title": title.replace("AI", topic[:6] if topic else "AI"),
                "year": year,
                "angle": angle,
                "claim": f"围绕「{topic}」提出一个可检验的核心论点，并给出研究推进路径。",
                "method": method,
            }
        )
    return out

def _build_evidence(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    为右侧 Evidence 面板生成“作品版占位证据”
    link 为空字符串：前端会置灰“打开来源”
    """
    sources = ["CNKI", "Google Scholar", "arXiv", "图书"]
    trusts = ["高", "中", "低"]
    ev = []
    for p in papers:
        pid = int(p.get("id", 0) or 0)
        if pid <= 0:
            continue
        ev.append(
            {
                "id": pid,
                "candidateId": pid,
                "source": sources[(pid - 1) % len(sources)],
                "trust": trusts[(pid - 1) % len(trusts)],
                "title": p.get("title", "未命名文献"),
                "points": [
                    f"来源标记：{sources[(pid - 1) % len(sources)]}；可信度：{trusts[(pid - 1) % len(trusts)]}",
                    "占位信息：可扩展作者/期刊/被引/关键词等字段",
                ],
                "link": "",
            }
        )
    return ev

def _provider_try_order() -> List[str]:
    if LLM_PROVIDER == "auto":
        return ["zhipu", "gemini", "stub"]
    if LLM_PROVIDER in ("zhipu", "gemini", "stub"):
        return [LLM_PROVIDER]
    return ["zhipu", "gemini", "stub"]

def _call_llm_with_fallback(prompt: str) -> Tuple[str, str, bool, Optional[str]]:
    """
    Returns: (raw_text, provider_used, fallback_to_stub, last_error)
    """
    last_err = None
    order = _provider_try_order()

    for prov in order:
        try:
            if prov == "zhipu":
                return _call_zhipu(prompt), "zhipu", False, None
            if prov == "gemini":
                return _call_gemini(prompt), "gemini", False, None
            if prov == "stub":
                return "", "stub", True, (str(last_err) if last_err else None)
        except Exception as e:
            last_err = e
            if DEBUG:
                print(f"[{prov}] failed: {repr(e)}")
            if LLM_PROVIDER != "auto":
                raise

    if last_err:
        raise RuntimeError(str(last_err))
    return "", "stub", True, None

# ----------------------------
# Business
# ----------------------------
def generate_candidates(topic: str) -> Dict[str, Any]:
    prompt = f"""
你是一名学术检索引擎。
请基于研究主题，生成 6 条近年（2020–2025）的学术研究候选条目（允许合理模拟）。

【只输出 JSON 数组，不要输出任何解释性文字，不要输出 markdown。】

每条对象必须包含字段：
id（整数，从1开始）
title（论文标题）
year（年份）
angle（理论视角，如：实践哲学 / 主体性重构 / 技术批判）
claim（一句话核心观点，控制在 30–45 字）
method（研究方法，如：理论阐释 / 文本分析 / 比较研究）

研究主题：{topic}
""".strip()

    raw, provider_used, fallback, last_error = _call_llm_with_fallback(prompt)

    if provider_used == "stub":
        papers = _stub_candidates(topic)
    else:
        raw_clean = _extract_json_array(raw)
        papers = _safe_json_loads(raw_clean, [])
        if not isinstance(papers, list) or len(papers) == 0:
            papers = _stub_candidates(topic)
            provider_used = "stub"
            fallback = True

    for i, p in enumerate(papers, start=1):
        if isinstance(p, dict):
            p["id"] = int(p.get("id") or i)
            p.setdefault("year", 2024)
            p.setdefault("angle", "")
            p.setdefault("claim", "")
            p.setdefault("method", "")

    evidence = _build_evidence(papers)

    meta = {
        "provider_config": LLM_PROVIDER,
        "provider_used": provider_used,
        "fallback_to_stub": bool(fallback),
        "model": (
            ZHIPU_MODEL if provider_used == "zhipu"
            else GEMINI_MODEL if provider_used == "gemini"
            else "stub"
        ),
        "last_error": last_error,
    }

    return {"topic": topic, "papers": papers, "evidence": evidence, "meta": meta}

def generate_synthesis(topic: str, selected_ids: List[int]) -> Dict[str, Any]:
    prompt = f"""
你是一名研究助理。
请围绕主题输出“研究脉络与选题”的短文（中文），要求结构如下（必须包含）：
---
### 1) 这组研究的共同问题意识
（2-4 句）
### 2) 可能的研究脉络/分歧（2–3 条主线）
（用列表）
### 3) 三个可写的选题方向（含创新点）
（编号列表，3条）
---

主题：{topic}
被选中的候选条目 id：{selected_ids}
""".strip()

    raw, provider_used, fallback, last_error = _call_llm_with_fallback(prompt)
    text = (raw or "").strip()

    if provider_used == "stub" or len(text) < 20:
        text = f"（stub）主题：{topic}；已选：{selected_ids}\n\n请先打通真实模型后再生成完整研究脉络。"
        provider_used = "stub"
        fallback = True

    meta = {
        "provider_config": LLM_PROVIDER,
        "provider_used": provider_used,
        "fallback_to_stub": bool(fallback),
        "model": (
            ZHIPU_MODEL if provider_used == "zhipu"
            else GEMINI_MODEL if provider_used == "gemini"
            else "stub"
        ),
        "last_error": last_error,
    }
    return {"topic": topic, "text": text, "meta": meta}

# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "provider": LLM_PROVIDER,
        "zhipu_model": ZHIPU_MODEL,
        "gemini_model": GEMINI_MODEL,
        "has_zhipu_key": bool(ZHIPU_API_KEY),
        "has_gemini_key": bool(GEMINI_API_KEY),
        "debug": DEBUG,
        "timestamp": int(time.time()),
    }

# Core routes
@app.get("/candidates")
def candidates(topic: str):
    topic = (topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    return generate_candidates(topic)

@app.post("/synthesis")
def synthesis(req: SynthesisReq):
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    return generate_synthesis(topic, req.selectedIds)

# Compatibility: /api prefix
@app.get("/api/candidates")
def api_candidates(topic: str):
    return candidates(topic)

@app.post("/api/synthesis")
def api_synthesis(req: SynthesisReq):
    return synthesis(req)
