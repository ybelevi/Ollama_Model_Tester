#!/usr/bin/env python3
"""
Ollama Model Tester - FastAPI Backend
Proxy, test runner, dosya servisi
"""

import os
import sys
import json
import time
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
PROMPTS_DIR = BASE_DIR / "prompts"
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"
STATIC_DIR = BASE_DIR / "static"

RESULTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

OLLAMA_DEFAULT_HOST = "http://192.168.240.30:11434"
OLLAMA_SSH_HOST = "192.168.240.30"  # Ollama sunucusu SSH adresi
OLLAMA_SSH_PORT = 22
API_TIMEOUT = 300
PROMPT_TIMEOUT_SECONDS = 240  # Normal prompt timeout (4 dk)
WARMUP_TIMEOUT_SECONDS = 300  # İlk prompt için model yükleme süresi

# SSH Config file (stores credentials securely-ish)
SSH_CONFIG_FILE = BASE_DIR / "config" / "ssh_config.json"
SSH_CONFIG_FILE.parent.mkdir(exist_ok=True)

# Model Capabilities Cache (fetched from Ollama website)
CAPABILITIES_CACHE_FILE = BASE_DIR / "config" / "model_capabilities_cache.json"


def _load_capabilities_cache() -> Dict[str, Any]:
    """Load cached model capabilities from file. Returns {model: {capabilities: [], cached_at: timestamp}}."""
    if CAPABILITIES_CACHE_FILE.exists():
        try:
            with open(CAPABILITIES_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Migrate old format {model: [caps]} to new format {model: {capabilities: [caps], cached_at: ts}}
            migrated = {}
            for key, val in data.items():
                if isinstance(val, list):
                    migrated[key] = {"capabilities": val, "cached_at": 0}  # Force refresh on old entries
                elif isinstance(val, dict) and "capabilities" in val:
                    migrated[key] = val
            return migrated
        except Exception:
            pass
    return {}


def _save_capabilities_cache(cache: Dict[str, Any]):
    """Save model capabilities cache to file."""
    CAPABILITIES_CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CAPABILITIES_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _fetch_model_capabilities(model_name: str) -> List[str]:
    """Fetch capabilities from Ollama model page (vision, tools, thinking)."""
    import urllib.request
    import re

    # Remove tag (e.g., qwen3.5:9b -> qwen3.5)
    base_name = model_name.split(':')[0].split('/')[-1]

    cache = _load_capabilities_cache()
    if base_name in cache:
        entry = cache[base_name]
        # Check if cache is fresh (7 days)
        cached_at = entry.get("cached_at", 0)
        if time.time() - cached_at < 604800:  # 7 days in seconds
            return entry.get("capabilities", [])
        # Stale cache, will refresh below

    try:
        url = f"https://ollama.com/library/{base_name}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8')

        # Only look at upper part of page (before Readme section)
        upper_html = html.split('Readme')[0] if 'Readme' in html else html[:50000]

        # Strip HTML tags and normalize whitespace for plain-text search
        text = re.sub(r'<[^>]+>', ' ', upper_html)
        text = re.sub(r'\s+', ' ', text)

        capabilities = []
        for cap in ['vision', 'tools', 'thinking']:
            # Search for whole word capability in page text
            if re.search(rf'\b{cap}\b', text, re.IGNORECASE):
                capabilities.append(cap)

        print(f"[CAPABILITIES] {base_name}: {capabilities}")

        # Cache the result with timestamp
        cache[base_name] = {"capabilities": capabilities, "cached_at": time.time()}
        _save_capabilities_cache(cache)

        return capabilities
    except Exception as e:
        print(f"[CAPABILITIES ERROR] {base_name}: {e}")
        return []


app = FastAPI(title="Ollama Model Tester", version="1.0.0")

# CORS - allow all for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_prompts(category: str) -> List[Dict[str, Any]]:
    path = PROMPTS_DIR / f"{category}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt file not found: {category}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_categories() -> Dict[str, List[Dict[str, Any]]]:
    cats = {}
    for p in PROMPTS_DIR.glob("*.json"):
        cats[p.stem] = load_prompts(p.stem)
    return cats


async def ollama_request(host: str, endpoint: str, payload: Optional[Dict[str, Any]] = None, method: str = "POST") -> Dict[str, Any]:
    """Raw HTTP request to Ollama (no requests dependency)."""
    import urllib.request
    url = host.rstrip("/") + endpoint
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )
    loop = asyncio.get_event_loop()
    def _fetch():
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}
    return await loop.run_in_executor(None, _fetch)


async def ollama_generate(host: str, model: str, prompt: str, num_predict: int = 8192, timeout_sec: int = API_TIMEOUT) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": num_predict,
        }
    }
    # Custom timeout for this specific request
    import urllib.request
    url = host.rstrip("/") + "/api/generate"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    loop = asyncio.get_event_loop()
    def _fetch():
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"error": str(e)}
    future = loop.run_in_executor(None, _fetch)
    try:
        resp = await asyncio.wait_for(future, timeout=timeout_sec)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Request timeout after {timeout_sec}s")
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp.get("response", "")


# ---------------------------------------------------------------------------
# Model Unload Helper
# ---------------------------------------------------------------------------

async def unload_model_from_gpu(host: str, model: str):
    """Unload model from Ollama GPU memory after test completion."""
    try:
        # Ollama keep_alive: 0 means unload immediately after this request
        payload = {
            "model": model,
            "prompt": "",
            "keep_alive": 0,
            "stream": False,
            "options": {"num_predict": 1}
        }
        await ollama_request(host, "/api/generate", payload=payload, method="POST")
        print(f"[INFO] Model {model} unloaded from GPU")
    except Exception as e:
        print(f"[WARN] Failed to unload model {model}: {e}")


# ---------------------------------------------------------------------------
# Global test state (in-memory + file backed)
# ---------------------------------------------------------------------------

_test_states: Dict[str, Dict[str, Any]] = {}


def _save_state(run_id: str, state: Dict[str, Any]):
    path = LOGS_DIR / f"status_{run_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    _test_states[run_id] = state


def _load_state(run_id: str) -> Optional[Dict[str, Any]]:
    if run_id in _test_states:
        return _test_states[run_id]
    path = LOGS_DIR / f"status_{run_id}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
            _test_states[run_id] = state
            return state
    return None


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

def _cleanup_old_results(model: str):
    """Remove old result directories and status files for the same model."""
    import shutil
    safe_model = model.replace(":", "_").replace("/", "_")
    removed = 0

    # Scan results dir
    if RESULTS_DIR.exists():
        for entry in RESULTS_DIR.iterdir():
            if not entry.is_dir():
                continue
            # Check if dir name starts with model name
            if entry.name.startswith(safe_model + "_"):
                try:
                    shutil.rmtree(entry)
                    removed += 1
                except Exception as e:
                    print(f"[WARN] Failed to remove old result dir {entry}: {e}")

    # Also clean old status files from logs dir (matching model in state)
    if LOGS_DIR.exists():
        for entry in LOGS_DIR.glob("status_*.json"):
            try:
                with open(entry, "r", encoding="utf-8") as f:
                    st = json.load(f)
                if st.get("model") == model:
                    entry.unlink()
            except Exception:
                pass

    if removed > 0:
        print(f"[INFO] Cleaned up {removed} old result(s) for model {model}")


async def run_test_task(run_id: str, host: str, model: str, categories: List[str]):
    """Background task: run all selected prompts against model with timeout and stop support."""
    # Clean up old results for the same model
    _cleanup_old_results(model)

    start_time = time.time()
    all_prompts: List[Dict[str, Any]] = []
    for cat in categories:
        try:
            ps = load_prompts(cat)
            for p in ps:
                p["_category"] = cat
            all_prompts.extend(ps)
        except Exception as e:
            print(f"[WARN] Failed to load category {cat}: {e}")

    total = len(all_prompts)
    state = {
        "run_id": run_id,
        "model": model,
        "host": host,
        "categories": categories,
        "total": total,
        "completed": 0,
        "timeouts": 0,
        "current_prompt_id": None,
        "current_category": None,
        "status": "running",  # running | paused | completed | error | cancelled
        "start_time": start_time,
        "end_time": None,
        "logs": [],
        "results_dir": None,
    }
    _save_state(run_id, state)

    # Create results dir
    safe_model = model.replace(":", "_").replace("/", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_DIR / f"{safe_model}_{ts}"
    run_dir.mkdir(exist_ok=True)
    state["results_dir"] = str(run_dir.relative_to(BASE_DIR))
    _save_state(run_id, state)

    # Manifest
    manifest = {
        "run_id": run_id,
        "model": model,
        "host": host,
        "categories": categories,
        "total_prompts": total,
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "duration_sec": None,
    }

    history: Dict[str, str] = {}
    completed_ids = set()
    timeout_count = 0

    # Check if model is already loaded in GPU memory
    model_loaded = False
    try:
        ps_resp = await ollama_request(host, "/api/ps", payload=None, method="GET")
        for m in ps_resp.get("models", []):
            if m.get("model") == model or m.get("name") == model:
                model_loaded = True
                break
    except Exception:
        pass

    if model_loaded:
        state["logs"].append("[WARMUP] Model zaten bellekte yüklü, warmup atlanıyor...")
        state["logs"].append("  -> Warmup OK (cached)")
    else:
        # Warmup: Send a trivial prompt to load model into memory
        msg = "[WARMUP] Model belleğe yükleniyor, lütfen bekleyin..."
        state["logs"].append(msg)
        state["current_prompt_id"] = "__warmup__"
        _save_state(run_id, state)
        try:
            await ollama_generate(host, model, "Say 'OK'", num_predict=10, timeout_sec=WARMUP_TIMEOUT_SECONDS)
            state["logs"].append("  -> Warmup OK")
        except Exception as e:
            state["logs"].append(f"  -> Warmup FAILED: {e}")
            state["status"] = "error"
            _save_state(run_id, state)
            return

    for idx, item in enumerate(all_prompts, 1):
        # Check pause or cancelled
        while True:
            st = _load_state(run_id)
            if st and st.get("status") == "cancelled":
                state["logs"].append("TEST CANCELLED BY USER.")
                _save_state(run_id, state)
                return
            if st and st.get("status") == "paused":
                await asyncio.sleep(1)
                continue
            if st and st.get("status") == "error":
                return
            break

        prompt_text = item["prompt"]
        dep = item.get("depends_on")
        if dep and dep in history:
            prev = history[dep]
            prompt_text = f"[Previous Work]\n---\n{prev}\n---\nNew Task: {item['prompt']}"
        elif dep and dep not in history:
            msg = f"[{idx}/{total}] {item['id']} | Dependency {dep} missing, skipping."
            state["logs"].append(msg)
            _save_state(run_id, state)
            continue

        msg = f"[{idx}/{total}] {item['id']} | {item['_category']} | Running..."
        state["logs"].append(msg)
        state["current_prompt_id"] = item["id"]
        state["current_category"] = item["_category"]
        _save_state(run_id, state)

        t0 = time.time()
        response = None
        timed_out = False
        prompt_timeout = 300 if item["_category"] == "thinking" else 240

        try:
            response = await ollama_generate(host, model, prompt_text, timeout_sec=prompt_timeout)
            dur = time.time() - t0
            history[item["id"]] = response
            completed_ids.add(item["id"])

            # Save result
            cat_dir = run_dir / item["_category"]
            cat_dir.mkdir(exist_ok=True)
            result_obj = {
                "id": item["id"],
                "category": item["_category"],
                "prompt": item["prompt"],
                "response": response,
                "duration_sec": round(dur, 1),
                "timestamp": datetime.now().isoformat(),
                "expected_focus": item.get("expected_focus", []),
                "ai_evaluation": {
                    "correctness": "pending",
                    "hallucination": None,
                    "security_aware": None,
                    "completeness": "pending",
                    "idiomatic": None,
                    "notes": "AI evaluation pending."
                }
            }
            with open(cat_dir / f"{item['id']}.json", "w", encoding="utf-8") as f:
                json.dump(result_obj, f, ensure_ascii=False, indent=2)

            ok_msg = f"  -> OK ({dur:.1f}s)"
            state["logs"].append(ok_msg)
        except asyncio.TimeoutError:
            timed_out = True
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                timed_out = True
            else:
                state["logs"].append(f"  -> ERROR: {e}")

        if timed_out:
            timeout_count += 1
            dur = time.time() - t0
            state["logs"].append(f"  -> TIMEOUT ({dur:.1f}s / limit {prompt_timeout}s)")
            # Save timeout result
            cat_dir = run_dir / item["_category"]
            cat_dir.mkdir(exist_ok=True)
            result_obj = {
                "id": item["id"],
                "category": item["_category"],
                "prompt": item["prompt"],
                "response": f"[TIMEOUT] Model {prompt_timeout} saniye içinde cevap vermedi.",
                "duration_sec": round(dur, 1),
                "timestamp": datetime.now().isoformat(),
                "expected_focus": item.get("expected_focus", []),
                "ai_evaluation": {
                    "correctness": "timeout",
                    "hallucination": False,
                    "security_aware": None,
                    "completeness": "timeout",
                    "idiomatic": None,
                    "notes": f"Prompt {prompt_timeout} sn timeout'a uğradı."
                }
            }
            with open(cat_dir / f"{item['id']}.json", "w", encoding="utf-8") as f:
                json.dump(result_obj, f, ensure_ascii=False, indent=2)
            # Mark as completed so we don't hang
            completed_ids.add(item["id"])

        state["completed"] = len(completed_ids)
        state["timeouts"] = timeout_count
        _save_state(run_id, state)
        await asyncio.sleep(0.5)

    # Finalize
    total_elapsed = time.time() - start_time
    manifest["end_time"] = datetime.now().isoformat()
    manifest["duration_sec"] = round(total_elapsed, 1)
    manifest["timeouts"] = timeout_count
    with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    state["status"] = "completed"
    state["end_time"] = time.time()
    state["logs"].append(f"TEST COMPLETED. Total: {total_elapsed/60:.1f} min | Timeouts: {timeout_count}")
    _save_state(run_id, state)

    # Unload model from GPU to free VRAM
    await unload_model_from_gpu(host, model)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/models")
async def list_models(host: str = Query(default=OLLAMA_DEFAULT_HOST)):
    try:
        resp = await ollama_request(host, "/api/tags", payload=None, method="GET")
        if "error" in resp:
            raise HTTPException(status_code=502, detail=resp["error"])
        models = resp.get("models", [])

        # Fetch capabilities for each model
        result = []
        for m in models:
            model_name = m["name"]
            print(f"[API] Fetching capabilities for: {model_name}")
            capabilities = _fetch_model_capabilities(model_name)
            print(f"[API] Result for {model_name}: {capabilities}")
            result.append({
                "name": model_name,
                "size": m.get("size"),
                "capabilities": capabilities,
            })

        return {"host": host, "models": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/prompts/{category}")
async def get_prompts(category: str):
    try:
        prompts = load_prompts(category)
        return {"category": category, "count": len(prompts), "prompts": prompts}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _cancel_all_active_tests():
    """Cancel any running/paused tests, unload models, and clean up incomplete results."""
    import shutil
    for run_id, state in list(_test_states.items()):
        if state.get("status") in ("running", "paused"):
            # Unload model from GPU first
            try:
                await unload_model_from_gpu(state.get("host", OLLAMA_DEFAULT_HOST), state.get("model", ""))
            except Exception:
                pass
            # Mark as cancelled
            state["status"] = "cancelled"
            state["logs"].append("[SYSTEM] Yeni test başlatıldığı için iptal edildi. Model GPU belleğinden atıldı.")
            _save_state(run_id, state)
            # Remove incomplete results directory
            results_dir = state.get("results_dir")
            if results_dir:
                d = BASE_DIR / results_dir
                if d.exists():
                    try:
                        shutil.rmtree(d)
                    except Exception:
                        pass
            # Remove status file
            sf = LOGS_DIR / f"status_{run_id}.json"
            if sf.exists():
                try:
                    sf.unlink()
                except Exception:
                    pass


@app.post("/api/test/start")
async def start_test(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any]
):
    host = payload.get("host", OLLAMA_DEFAULT_HOST)
    model = payload.get("model")
    categories = payload.get("categories", [])
    force = payload.get("force", False)  # Kullanıcı onayladı mı?
    if not model:
        raise HTTPException(status_code=400, detail="Model name required")
    if not categories:
        raise HTTPException(status_code=400, detail="At least one category required")

    # MUTLAKA: Önce tüm aktif testleri iptal et, modelleri GPU'dan at ve sonuçlarını sil
    await _cancel_all_active_tests()

    # Check Ollama'da yüklü model
    loaded_model = None
    try:
        resp = await ollama_request(host, "/api/tags", payload=None, method="GET")
        models = resp.get("models", [])
        # En son kullanılan modeli tahmin et (bu bir tahmin, tam doğru olmayabilir)
        if models:
            loaded_model = models[0]["name"]  # İlk modeli varsayalım
    except Exception:
        pass

    # ALWAYS restart Ollama before new test to clear any lingering state
    restart_info = None
    try:
        cfg = _load_ssh_config()
        if cfg.get("username"):
            await _ssh_execute_command("systemctl daemon-reload")
            await _ssh_execute_command("systemctl restart ollama")
            # Wait for Ollama to fully start before launching test
            await asyncio.sleep(15)
            restart_info = "ℹ️ Ollama sunucusu otomatik olarak yeniden başlatıldı (15sn beklendi). Bellek temizlendi, yeni test güvenli başlıyor."
        else:
            restart_info = "⚠️ SSH yapılandırılmamış. Ollama restart edilemedi. Eski test kalıntıları yeni testi etkileyebilir."
    except Exception as e:
        restart_info = f"⚠️ Ollama restart başarısız: {e}. Eski test kalıntıları yeni testi etkileyebilir."

    run_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(run_test_task, run_id, host, model, categories)
    return {
        "run_id": run_id,
        "status": "started",
        "loaded_model": loaded_model,
        "restart_info": restart_info,
    }


@app.get("/api/test/status/{run_id}")
async def test_status(run_id: str):
    state = _load_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run ID not found")
    return state


@app.post("/api/test/pause/{run_id}")
async def pause_test(run_id: str):
    state = _load_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run ID not found")
    state["status"] = "paused"
    _save_state(run_id, state)
    return {"status": "paused"}


@app.post("/api/test/resume/{run_id}")
async def resume_test(run_id: str):
    state = _load_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run ID not found")
    state["status"] = "running"
    _save_state(run_id, state)
    return {"status": "running"}


@app.post("/api/test/stop/{run_id}")
async def stop_test(run_id: str):
    state = _load_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run ID not found")
    state["status"] = "cancelled"
    _save_state(run_id, state)
    # Unload model from GPU to free VRAM
    await unload_model_from_gpu(state.get("host", OLLAMA_DEFAULT_HOST), state.get("model", ""))
    return {"status": "cancelled"}


@app.get("/api/test/active")
async def active_tests():
    """List all currently running or paused tests."""
    active = []
    for run_id, state in _test_states.items():
        if state.get("status") in ("running", "paused"):
            active.append({
                "run_id": run_id,
                "model": state.get("model"),
                "status": state.get("status"),
                "completed": state.get("completed", 0),
                "total": state.get("total", 0),
                "current_prompt": state.get("current_prompt_id"),
            })
    return {"active": active}


@app.get("/api/model-capabilities")
async def get_model_capabilities(name: str = Query(..., description="Model name (e.g. qwen3.5:9b)")):
    """Get capabilities for a single model (fast, no full model list needed)."""
    capabilities = _fetch_model_capabilities(name)
    return {"model": name, "capabilities": capabilities}


@app.get("/api/results")
async def list_results():
    results = []
    for d in sorted(RESULTS_DIR.iterdir()):
        if d.is_dir():
            mfile = d / "manifest.json"
            if mfile.exists():
                with open(mfile, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                results.append({
                    "id": d.name,
                    "manifest": manifest,
                })
    return {"results": results}


def _resolve_result_dir(result_id: str):
    d = RESULTS_DIR / result_id
    if d.exists():
        return d
    # Try matching by run_id in manifest
    for subdir in RESULTS_DIR.iterdir():
        if subdir.is_dir():
            mfile = subdir / "manifest.json"
            if mfile.exists():
                with open(mfile, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                if manifest.get("run_id") == result_id:
                    return subdir
    return None


@app.get("/api/results/{result_id}")
async def get_result(result_id: str):
    d = _resolve_result_dir(result_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Result not found")
    manifest = {}
    mfile = d / "manifest.json"
    if mfile.exists():
        with open(mfile, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    # Load category results
    categories = {}
    for cat_dir in d.iterdir():
        if cat_dir.is_dir():
            cat_results = []
            for jf in cat_dir.glob("*.json"):
                with open(jf, "r", encoding="utf-8") as f:
                    cat_results.append(json.load(f))
            categories[cat_dir.name] = cat_results
    return {"id": result_id, "manifest": manifest, "categories": categories}


@app.post("/api/compare")
async def compare_results(payload: Dict[str, Any]):
    result_ids = payload.get("result_ids", [])
    if len(result_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 results required")

    # Load all manifests
    data = []
    for rid in result_ids:
        d = RESULTS_DIR / rid
        if not d.exists():
            continue
        mfile = d / "manifest.json"
        manifest = {}
        if mfile.exists():
            with open(mfile, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        categories = {}
        for cat_dir in d.iterdir():
            if cat_dir.is_dir():
                cat_results = {}
                for jf in cat_dir.glob("*.json"):
                    with open(jf, "r", encoding="utf-8") as f:
                        obj = json.load(f)
                    cat_results[obj["id"]] = obj
                categories[cat_dir.name] = cat_results
        data.append({
            "id": rid,
            "model": manifest.get("model", "unknown"),
            "manifest": manifest,
            "categories": categories,
        })

    # Build prompt-level comparison table
    prompt_table = {}
    for entry in data:
        for cat_name, cat_data in entry["categories"].items():
            for pid, pobj in cat_data.items():
                if pid not in prompt_table:
                    prompt_table[pid] = {
                        "id": pid,
                        "category": cat_name,
                        "prompt": pobj["prompt"][:200] + "...",
                        "models": {}
                    }
                prompt_table[pid]["models"][entry["model"]] = {
                    "duration_sec": pobj.get("duration_sec"),
                    "response_preview": pobj["response"][:300] + "..." if len(pobj["response"]) > 300 else pobj["response"],
                }

    # Build model summary (category-level scores)
    all_categories = set()
    for entry in data:
        all_categories.update(entry["categories"].keys())

    model_summaries = []
    for entry in data:
        model_name = entry["model"]
        manifest = entry["manifest"]
        categories = entry["categories"]
        summary = {
            "model": model_name,
            "total_prompts": manifest.get("total_prompts", 0),
            "duration_sec": manifest.get("duration_sec", 0),
            "categories": {}
        }
        for cat_name in sorted(all_categories):
            if cat_name in categories:
                cat_data = categories[cat_name]
                passed = sum(1 for v in cat_data.values() if v.get("ai_evaluation", {}).get("correctness") in ("passed", "full"))
                failed = sum(1 for v in cat_data.values() if v.get("ai_evaluation", {}).get("correctness") in ("failed",))
                timeout = sum(1 for v in cat_data.values() if "[TIMEOUT]" in v.get("response", ""))
                partial = sum(1 for v in cat_data.values() if v.get("ai_evaluation", {}).get("correctness") in ("partial",))
                total = len(cat_data)
                summary["categories"][cat_name] = {
                    "status": "tested",
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "partial": partial,
                    "timeout": timeout,
                }
            else:
                summary["categories"][cat_name] = {
                    "status": "not_tested",
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "partial": 0,
                    "timeout": 0,
                }
        model_summaries.append(summary)

    return {
        "models": [d["model"] for d in data],
        "comparison_table": list(prompt_table.values()),
        "model_summaries": model_summaries,
    }


@app.get("/api/export/{result_id}")
async def export_result(result_id: str):
    d = _resolve_result_dir(result_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Result not found")
    # Return manifest for now; could zip later
    mfile = d / "manifest.json"
    if mfile.exists():
        return FileResponse(mfile, media_type="application/json", filename=f"{result_id}_manifest.json")
    raise HTTPException(status_code=404, detail="Manifest not found")


# ---------------------------------------------------------------------------
# Admin Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SSH Helpers for Remote Ollama Server Management
# ---------------------------------------------------------------------------

def _load_ssh_config() -> Dict[str, Any]:
    """Load SSH credentials from config file."""
    if SSH_CONFIG_FILE.exists():
        try:
            with open(SSH_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_ssh_config(config: Dict[str, Any]):
    """Save SSH credentials to config file."""
    with open(SSH_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


async def _ssh_execute_command(command: str) -> Dict[str, Any]:
    """Execute a command on the remote Ollama server via SSH."""
    cfg = _load_ssh_config()
    if not cfg.get("username") or not cfg.get("password"):
        return {"success": False, "error": "SSH credentials not configured. Go to Sistem page to set them."}

    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=cfg.get("host", OLLAMA_SSH_HOST),
            port=cfg.get("port", OLLAMA_SSH_PORT),
            username=cfg["username"],
            password=cfg["password"],
            timeout=30,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=60)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8").strip()
        err = stderr.read().decode("utf-8").strip()
        client.close()
        return {
            "success": exit_code == 0,
            "exit_code": exit_code,
            "stdout": out,
            "stderr": err,
        }
    except ImportError:
        return {"success": False, "error": "paramiko library not installed. Run: pip install paramiko"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/admin/ssh-config")
async def get_ssh_config():
    """Get current SSH config (without password)."""
    cfg = _load_ssh_config()
    return {
        "configured": bool(cfg.get("username")),
        "host": cfg.get("host", OLLAMA_SSH_HOST),
        "port": cfg.get("port", OLLAMA_SSH_PORT),
        "username": cfg.get("username", ""),
        "has_password": bool(cfg.get("password")),
    }


@app.post("/api/admin/ssh-config")
async def set_ssh_config(payload: Dict[str, Any]):
    """Save SSH credentials."""
    config = {
        "host": payload.get("host", OLLAMA_SSH_HOST),
        "port": payload.get("port", OLLAMA_SSH_PORT),
        "username": payload.get("username", ""),
        "password": payload.get("password", ""),
    }
    if not config["username"] or not config["password"]:
        raise HTTPException(status_code=400, detail="Username and password required")
    _save_ssh_config(config)
    return {"success": True, "message": "SSH configuration saved"}


@app.post("/api/admin/ssh-test")
async def test_ssh_connection():
    """Test SSH connection to Ollama server."""
    result = await _ssh_execute_command("echo 'SSH_OK'")
    if result["success"] and "SSH_OK" in result.get("stdout", ""):
        return {"success": True, "message": "SSH connection successful"}
    return {"success": False, "error": result.get("error") or result.get("stderr", "Connection failed")}


@app.post("/api/admin/restart-ollama")
async def restart_ollama():
    """
    Restart the Ollama service on the remote server via SSH.
    Requires SSH credentials to be configured first.
    """
    cfg = _load_ssh_config()
    if not cfg.get("username"):
        return {
            "success": False,
            "message": "SSH bağlantısı yapılandırılmamış.",
            "instructions": "Sistem sayfasına gidin ve SSH bilgilerinizi kaydedin.",
            "commands": ["sudo systemctl daemon-reload", "sudo systemctl restart ollama"],
        }

    # Execute restart commands
    result1 = await _ssh_execute_command("systemctl daemon-reload")
    result2 = await _ssh_execute_command("systemctl restart ollama")

    if result2["success"]:
        return {
            "success": True,
            "message": "Ollama sunucusu başarıyla yeniden başlatıldı.",
            "details": {
                "daemon_reload": result1.get("stdout", ""),
                "restart": result2.get("stdout", ""),
            }
        }
    else:
        return {
            "success": False,
            "message": "Ollama yeniden başlatılamadı.",
            "error": result2.get("error") or result2.get("stderr", "Unknown error"),
        }


@app.get("/api/admin/ollama-ps")
async def ollama_ps(host: str = Query(default=OLLAMA_DEFAULT_HOST)):
    """
    Proxy to Ollama's /api/ps endpoint.
    Returns running models with GPU/VRAM and CPU/RAM usage info.
    """
    try:
        resp = await ollama_request(host, "/api/ps", payload=None, method="GET")
        if "error" in resp:
            raise HTTPException(status_code=502, detail=resp["error"])
        # Format the response nicely
        models = resp.get("models", [])
        formatted = []
        for m in models:
            formatted.append({
                "name": m.get("name"),
                "model": m.get("model"),
                "size": m.get("size"),
                "size_vram": m.get("size_vram"),
                "digest": m.get("digest"),
                "details": m.get("details", {}),
                "expires_at": m.get("expires_at"),
            })
        return {
            "host": host,
            "running_models": formatted,
            "count": len(formatted)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------------------------------
# GPU Monitoring (nvidia-ml-py / pynvml)
# ---------------------------------------------------------------------------

def _get_gpu_info() -> Dict[str, Any]:
    """Try to get GPU info via nvidia-ml-py. Returns empty if no GPU or library missing."""
    try:
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW to W
            gpus.append({
                "index": i,
                "name": name,
                "memory_total_mb": mem_info.total // (1024 * 1024),
                "memory_used_mb": mem_info.used // (1024 * 1024),
                "memory_free_mb": mem_info.free // (1024 * 1024),
                "gpu_utilization": util.gpu,
                "memory_utilization": util.memory,
                "temperature_c": temp,
                "power_w": power,
            })
        pynvml.nvmlShutdown()
        return {"available": True, "gpu_count": device_count, "gpus": gpus}
    except Exception as e:
        return {"available": False, "error": str(e), "gpus": []}


@app.get("/api/admin/gpu-info")
async def gpu_info():
    """
    Returns local GPU info via nvidia-ml-py.
    NOTE: For remote Ollama servers, run this backend on the same machine
    or set up SSH remote execution to monitor the server's GPU.
    """
    info = _get_gpu_info()
    return {
        "local_gpu": info,
        "note": "Bu bilgiler backend'in çalıştığı makineden gelir. "
                "Ollama sunucusu farklı bir makinedeyse GPU bilgileri görünmeyebilir. "
                "Remote GPU izlemek için backend'i Ollama sunucusunda çalıştırın veya SSH kurun.",
        "timestamp": datetime.now().isoformat()
    }


# ---------------------------------------------------------------------------
# System Check & Dependency Management
# ---------------------------------------------------------------------------

# Mapping: module import name -> pip package name
DEPENDENCIES = {
    "required": {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "starlette": "starlette",
    },
    "optional": {
        "pynvml": "nvidia-ml-py",
    }
}


def _check_module(module_name: str) -> bool:
    """Check if a Python module can be imported."""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def _get_python_info() -> Dict[str, Any]:
    """Get Python version and executable path."""
    import sys
    return {
        "version": sys.version,
        "version_info": list(sys.version_info),
        "executable": sys.executable,
        "platform": sys.platform,
    }


@app.get("/api/admin/system-check")
async def system_check():
    """
    Check all required and optional Python dependencies.
    Returns install instructions for missing packages.
    """
    python_info = _get_python_info()
    results = {
        "python": python_info,
        "required": {},
        "optional": {},
        "all_ok": True,
        "missing_required": [],
        "missing_optional": [],
    }

    for name, pip_pkg in DEPENDENCIES["required"].items():
        installed = _check_module(name)
        results["required"][name] = {
            "installed": installed,
            "pip_package": pip_pkg,
            "install_command": f"pip install {pip_pkg}",
        }
        if not installed:
            results["all_ok"] = False
            results["missing_required"].append(name)

    for name, pip_pkg in DEPENDENCIES["optional"].items():
        installed = _check_module(name)
        results["optional"][name] = {
            "installed": installed,
            "pip_package": pip_pkg,
            "install_command": f"pip install {pip_pkg}",
        }
        if not installed:
            results["missing_optional"].append(name)

    return results


@app.post("/api/admin/install")
async def install_package(payload: Dict[str, Any]):
    """
    Install a Python package via pip.
    Requires explicit package name for security.
    """
    package = payload.get("package")
    if not package:
        raise HTTPException(status_code=400, detail="Package name required")

    # Security: only allow known packages
    all_packages = {**DEPENDENCIES["required"], **DEPENDENCIES["optional"]}
    if package not in all_packages.values():
        raise HTTPException(status_code=403, detail=f"Package '{package}' not in allowed list")

    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return {"success": True, "package": package, "output": result.stdout}
        else:
            return {"success": False, "package": package, "error": result.stderr}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Ranking / Sıralama
# ---------------------------------------------------------------------------

@app.get("/api/ranking")
async def get_ranking():
    category_rankings_raw: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    prompt_rankings_raw: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for d in RESULTS_DIR.iterdir():
        if not d.is_dir():
            continue
        mfile = d / "manifest.json"
        if not mfile.exists():
            continue
        with open(mfile, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        model_name = manifest.get("model", d.name)
        result_id = manifest.get("run_id", d.name)

        for cat_dir in d.iterdir():
            if not cat_dir.is_dir():
                continue
            cat_name = cat_dir.name
            cat_total = 0.0
            cat_count = 0

            for jf in cat_dir.glob("*.json"):
                with open(jf, "r", encoding="utf-8") as f:
                    item = json.load(f)
                duration = item.get("duration_sec", 0)
                prompt_id = item.get("id", jf.stem)
                correctness = item.get("ai_evaluation", {}).get("correctness", "unknown")
                cat_total += duration
                cat_count += 1

                # Prompt bazlı — model adına göre grupla
                pr = prompt_rankings_raw.setdefault(prompt_id, {})
                model_tests = pr.setdefault(model_name, [])
                model_tests.append({
                    "duration": duration,
                    "result_id": result_id,
                    "correctness": correctness,
                    "category": cat_name,
                })

            # Kategori bazlı — model adına göre grupla
            if cat_count > 0:
                cr = category_rankings_raw.setdefault(cat_name, {})
                model_tests = cr.setdefault(model_name, [])
                model_tests.append({
                    "total_duration": round(cat_total, 2),
                    "avg_duration": round(cat_total / cat_count, 2),
                    "prompt_count": cat_count,
                    "result_id": result_id,
                })

    # Kategori bazlı — model gruplarını özetle ve sırala
    category_rankings: Dict[str, List[Dict[str, Any]]] = {}
    for cat_name, models in category_rankings_raw.items():
        cat_list = []
        for model_name, tests in models.items():
            all_avg = [t["avg_duration"] for t in tests]
            overall_avg = round(sum(all_avg) / len(all_avg), 2)
            tests.sort(key=lambda x: x["avg_duration"])
            cat_list.append({
                "model": model_name,
                "overall_avg_duration": overall_avg,
                "test_count": len(tests),
                "tests": tests,
            })
        cat_list.sort(key=lambda x: x["overall_avg_duration"])
        category_rankings[cat_name] = cat_list

    # Prompt bazlı — önce kategori, sonra prompt_id, en içte model grupları
    prompt_by_cat: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}
    for prompt_id, models in prompt_rankings_raw.items():
        for model_name, tests in models.items():
            cat_name = tests[0].get("category", "unknown") if tests else "unknown"
            cat_map = prompt_by_cat.setdefault(cat_name, {})
            pr_map = cat_map.setdefault(prompt_id, {})
            pr_map[model_name] = tests

    prompt_rankings: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for cat_name, prompts in prompt_by_cat.items():
        cat_prompts: Dict[str, List[Dict[str, Any]]] = {}
        for prompt_id, models in prompts.items():
            prompt_list = []
            for model_name, tests in models.items():
                all_dur = [t["duration"] for t in tests]
                overall_avg = round(sum(all_dur) / len(all_dur), 2)
                tests.sort(key=lambda x: x["duration"])
                prompt_list.append({
                    "model": model_name,
                    "overall_avg_duration": overall_avg,
                    "test_count": len(tests),
                    "tests": tests,
                })
            prompt_list.sort(key=lambda x: x["overall_avg_duration"])
            cat_prompts[prompt_id] = prompt_list
        prompt_rankings[cat_name] = cat_prompts

    return {
        "category_rankings": category_rankings,
        "prompt_rankings": prompt_rankings,
    }


# ---------------------------------------------------------------------------
# Marathon / Toplu Test
# ---------------------------------------------------------------------------

_marathon_states: Dict[str, Any] = {}
_scheduler_loop: Optional[asyncio.AbstractEventLoop] = None


def _infer_capabilities(model_name: str) -> List[str]:
    """Infer model capabilities from name."""
    name = model_name.lower()
    caps = ["coding", "tools", "embedding"]
    if "vision" in name or "vl" in name:
        caps.append("vision")
    if "think" in name or "r1" in name or "deepseek" in name or "qwen3" in name or "qwen3.5" in name or "lfm2.5" in name:
        caps.append("thinking")
    return sorted(set(caps))


async def _fetch_models_list(host: str) -> List[Dict[str, Any]]:
    """Fetch installed models from Ollama."""
    import urllib.request
    url = host.rstrip("/") + "/api/tags"
    loop = asyncio.get_event_loop()
    def _fetch():
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8")).get("models", [])
        except Exception:
            return []
    return await loop.run_in_executor(None, _fetch)


async def run_marathon_task(marathon_id: str, host: str):
    """Run tests for all installed models across their inferred capabilities."""
    for mid, st in _marathon_states.items():
        if st.get("status") == "running" and mid != marathon_id:
            _marathon_states[marathon_id] = {
                "marathon_id": marathon_id,
                "status": "skipped",
                "reason": f"Another marathon ({mid}) is already running",
                "started_at": datetime.now().isoformat(),
            }
            return

    state = {
        "marathon_id": marathon_id,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "host": host,
        "models_total": 0,
        "models_completed": 0,
        "current_model": None,
        "current_category": None,
        "completed_tests": [],
        "error": None,
    }
    _marathon_states[marathon_id] = state

    try:
        models = await _fetch_models_list(host)
        state["models_total"] = len(models)

        for model_info in models:
            model_name = model_info.get("name") or model_info.get("model")
            if not model_name:
                continue
            categories = _infer_capabilities(model_name)
            state["current_model"] = model_name

            for cat in categories:
                state["current_category"] = cat
                run_id = str(uuid.uuid4())[:8]
                state["current_run_id"] = run_id
                task = asyncio.create_task(run_test_task(run_id, host, model_name, [cat]))
                while True:
                    await asyncio.sleep(5)
                    st = _load_state(run_id)
                    if st and st.get("status") in ("completed", "stopped", "failed", "error"):
                        break
                    if task.done():
                        break
                state["completed_tests"].append({
                    "model": model_name,
                    "category": cat,
                    "run_id": run_id,
                })
                state["models_completed"] = len(state["completed_tests"])

        state["status"] = "completed"
        state["ended_at"] = datetime.now().isoformat()
    except Exception as e:
        state["status"] = "failed"
        state["error"] = str(e)
        state["ended_at"] = datetime.now().isoformat()


@app.post("/api/marathon/start")
async def start_marathon(background_tasks: BackgroundTasks, host: Optional[str] = None):
    marathon_id = str(uuid.uuid4())[:8]
    target_host = host or OLLAMA_DEFAULT_HOST
    for mid, st in _marathon_states.items():
        if st.get("status") == "running":
            raise HTTPException(status_code=409, detail=f"Marathon {mid} is already running")
    background_tasks.add_task(run_marathon_task, marathon_id, target_host)
    return {"marathon_id": marathon_id, "status": "started", "host": target_host}


@app.get("/api/marathon/status/{marathon_id}")
async def get_marathon_status(marathon_id: str):
    state = _marathon_states.get(marathon_id)
    if not state:
        raise HTTPException(status_code=404, detail="Marathon not found")
    return state


@app.get("/api/marathon/latest")
async def get_latest_marathon():
    if not _marathon_states:
        raise HTTPException(status_code=404, detail="No marathon found")
    latest = max(_marathon_states.values(), key=lambda x: x.get("started_at", ""))
    return latest


def _start_scheduler():
    import threading
    import time

    def _check_and_run():
        last_run_date = None
        while True:
            now = datetime.now()
            today = now.date()
            if now.weekday() in (2, 6) and now.hour == 0 and now.minute == 0:
                if last_run_date != today:
                    last_run_date = today
                    marathon_id = str(uuid.uuid4())[:8]
                    target_host = OLLAMA_DEFAULT_HOST
                    if _scheduler_loop and _scheduler_loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            run_marathon_task(marathon_id, target_host),
                            _scheduler_loop,
                        )
                    time.sleep(3600)
            time.sleep(30)

    t = threading.Thread(target=_check_and_run, daemon=True)
    t.start()


@app.on_event("startup")
async def startup_event():
    global _scheduler_loop
    _scheduler_loop = asyncio.get_running_loop()
    _start_scheduler()


# ---------------------------------------------------------------------------
# Static Files
# ---------------------------------------------------------------------------

app.mount("/prompts", StaticFiles(directory=str(PROMPTS_DIR)), name="prompts")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
