#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
AI Latency Test - OpenRouter API
Tests response time for different models and payload sizes.
Usage: python3.11 tools/test_ai_latency.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import json
import time
import random
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Installing httpx...")
    import subprocess
    subprocess.check_call(["python3.11", "-m", "pip", "install", "httpx", "-q"])
    import httpx

try:
    from openai import OpenAI
except ImportError:
    print("Installing openai...")
    import subprocess
    subprocess.check_call(["python3.11", "-m", "pip", "install", "openai", "-q"])
    from openai import OpenAI


# ============================================================================
# CONFIGURATION
# ============================================================================

API_CONFIG_PATH = Path(__file__).parent.parent / "data" / "config.json"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 30

MODELS_TO_TEST = [
    "openrouter/free",
    "minimax/minimax-m2.5:free",
    "qwen/qwen3-4b:free",
    "google/gemma-3-4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]


# ============================================================================
# UTILITIES
# ============================================================================

def load_api_key() -> str:
    """Load OpenRouter API key from config file."""
    with open(API_CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    api_key = config.get("openrouter_api_key", "")
    if not api_key:
        raise ValueError("openrouter_api_key not found in data/config.json")
    
    # Mask for display
    masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
    print(f"API Key loaded: {masked}")
    return api_key


def generate_ohlcv_candles(count: int = 50) -> list:
    """Generate realistic OHLCV candle data for testing."""
    base_price = 150.0
    candles = []
    
    for i in range(count):
        timestamp = f"2026-03-{23-i:02d}T09:30:00"
        open_price = base_price + random.uniform(-2, 2)
        high = open_price + random.uniform(0, 3)
        low = open_price - random.uniform(0, 3)
        close = open_price + random.uniform(-1, 1)
        volume = random.randint(100000, 500000)
        
        candles.append({
            "timestamp": timestamp,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": volume
        })
        
        base_price = close
    
    return candles


def format_latency(seconds: float) -> str:
    """Format latency as string."""
    if seconds >= TIMEOUT_SECONDS:
        return "TIMEOUT"
    return f"{seconds:.1f}s"


# ============================================================================
# API CALLS
# ============================================================================

def call_openrouter(api_key: str, model: str, messages: list, 
                    max_tokens: int = 10, stream: bool = False) -> dict:
    """
    Call OpenRouter API and return response.
    Returns dict with keys: success, latency, first_token_latency (if streaming), error
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8050",
        "X-Title": "IB Trading Platform AI Test"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream
    }
    
    result = {
        "success": False,
        "latency": 0.0,
        "first_token_latency": None,
        "error": None,
        "response": None
    }
    
    start_time = time.time()
    
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            if stream:
                # Streaming request - measure time to first token
                response = client.post(
                    OPENROUTER_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=None  # Handled manually
                )
                response.raise_for_status()
                
                first_token_time = None
                full_response = ""
                
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]  # Remove "data: " prefix
                    
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            if first_token_time is None:
                                first_token_time = time.time()
                            full_response += content
                    except json.JSONDecodeError:
                        continue
                
                result["first_token_latency"] = first_token_time - start_time if first_token_time else None
                result["response"] = full_response
                
            else:
                # Non-streaming request
                response = client.post(
                    OPENROUTER_API_URL,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()
                result["response"] = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            result["latency"] = time.time() - start_time
            result["success"] = True
            
    except httpx.TimeoutException:
        result["error"] = "TIMEOUT"
        result["latency"] = TIMEOUT_SECONDS
    except Exception as e:
        result["error"] = str(e)
        result["latency"] = time.time() - start_time
    
    return result


# ============================================================================
# TESTS
# ============================================================================

def test_basic_latency(api_key: str) -> list:
    """Test 1: Basic latency with minimal payload."""
    print("\n" + "=" * 50)
    print("  TEST 1: Základní latence (prázdný payload)")
    print("=" * 50)
    print(f"{'Model':<40} {'Latence':<10} {'Status':<10}")
    print("-" * 60)
    
    results = []
    messages = [{"role": "user", "content": "Reply with one word: OK"}]
    
    for model in MODELS_TO_TEST:
        print(f"Testing {model}...", end=" ", flush=True)
        
        result = call_openrouter(api_key, model, messages, max_tokens=10)
        
        latency_str = format_latency(result["latency"])
        if result["success"]:
            status = "[OK]"
        else:
            status = f"[FAIL] {result['error']}"
        
        print(f"{latency_str:<10} {status}")
        
        results.append({
            "model": model,
            "latency": result["latency"],
            "success": result["success"],
            "error": result["error"]
        })
    
    return results


def test_real_payload(api_key: str, fastest_model: str) -> dict:
    """Test 2: Real trading payload with OHLCV data."""
    print("\n" + "=" * 50)
    print("  TEST 2: Reálný trading payload (simulate evaluate)")
    print("=" * 50)
    
    # Generate realistic payload
    candles = generate_ohlcv_candles(50)
    
    system_prompt = """You are an AI trading assistant. Analyze the provided OHLCV data 
and respond with a brief trading recommendation. Keep your response short."""
    
    user_content = f"""Analyze this market data and give a brief recommendation:

{candles}

Provide a short analysis (max 50 words)."""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    print(f"Model: {fastest_model}")
    print(f"Svíček: {len(candles)} | Prompt: ~{len(user_content)} znaků")
    print("Odesílám požadavek...", end=" ", flush=True)
    
    result = call_openrouter(api_key, fastest_model, messages, max_tokens=150)
    
    if result["success"]:
        print(f"{format_latency(result['latency'])} [OK]")
    else:
        print(f"[FAIL] {result['error']}")
    
    return result


def test_streaming_comparison(api_key: str, fastest_model: str) -> dict:
    """Test 3: Compare streaming vs non-streaming."""
    print("\n" + "=" * 50)
    print("  TEST 3: Streaming vs non-streaming")
    print("=" * 50)
    
    messages = [{"role": "user", "content": "Give me a brief market analysis in 2 sentences."}]
    
    results = {}
    
    # Non-streaming test
    print("Non-streaming test...", end=" ", flush=True)
    non_stream_result = call_openrouter(api_key, fastest_model, messages, 
                                         max_tokens=100, stream=False)
    
    if non_stream_result["success"]:
        print(f"{format_latency(non_stream_result['latency'])} (cela odpoved)")
        results["non_streaming"] = non_stream_result["latency"]
    else:
        print(f"[FAIL] {non_stream_result['error']}")
        results["non_streaming"] = None
    
    # Streaming test
    print("Streaming test...", end=" ", flush=True)
    stream_result = call_openrouter(api_key, fastest_model, messages, 
                                     max_tokens=100, stream=True)
    
    if stream_result["success"]:
        first_token = stream_result.get("first_token_latency")
        if first_token:
            speedup = results.get("non_streaming", 0) / first_token if first_token > 0 else 0
            print(f"{format_latency(first_token)} [OK] ({speedup:.1f}x rychlejsi)")
            results["streaming_first_token"] = first_token
            results["speedup"] = speedup
        else:
            print("[FAIL] Could not measure first token")
    else:
        print(f"[FAIL] {stream_result['error']}")
    
    return results


def test_minimax_reasoning(api_key: str) -> dict:
    """Dedicated MiniMax M2.5 test with reasoning parameter."""
    print("\n" + "=" * 50)
    print("  MiniMax M2.5 — Reasoning Test (OpenAI client)")
    print("=" * 50)
    
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key
    )
    
    result = {
        "success": False,
        "latency": 0.0,
        "error": None,
        "reasoning_available": False
    }
    
    print("Sending request with reasoning=True...", end=" ", flush=True)
    start = time.time()
    
    try:
        response = client.chat.completions.create(
            model="minimax/minimax-m2.5:free",
            messages=[{
                "role": "user",
                "content": "Reply with one word: OK"
            }],
            extra_body={"reasoning": {"enabled": True}},
            max_tokens=20,
            timeout=30
        )
        result["latency"] = time.time() - start
        
        content = response.choices[0].message.content
        print(f"{result['latency']:.1f}s [OK]")
        print(f"Odpověď: {content}")
        
        # Check for reasoning_details attribute
        reasoning = getattr(response.choices[0].message, 'reasoning_details', None)
        result["reasoning_available"] = reasoning is not None
        print(f"Reasoning details: {'ano' if reasoning else 'ne'}")
        
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
        result["latency"] = time.time() - start
        print(f"[FAIL] {e}")
    
    return result


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 50)
    print("  AI LATENCY TEST — OpenRouter")
    print("=" * 50)
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load API key
    try:
        api_key = load_api_key()
    except Exception as e:
        print(f"\n❌ Chyba při načítání API klíče: {e}")
        return
    
    # Test 1: Basic latency
    test1_results = test_basic_latency(api_key)
    
    # Find fastest successful model
    successful_models = [r for r in test1_results if r["success"]]
    
    if not successful_models:
        print("\n[FAIL] Zadny model neodpovedel uspesne!")
        return
    
    fastest = min(successful_models, key=lambda x: x["latency"])
    fastest_model = fastest["model"]
    
    print(f"\n*** Nejrychlejsi model: {fastest_model} ({format_latency(fastest['latency'])})")
    
    # Test 2: Real payload
    test2_result = test_real_payload(api_key, fastest_model)
    
    # Test 3: Streaming comparison
    test3_results = test_streaming_comparison(api_key, fastest_model)
    
    # MiniMax M2.5 reasoning test
    minimax_result = test_minimax_reasoning(api_key)
    
    # Summary
    print("\n" + "=" * 50)
    print("  SOUHRN")
    print("=" * 50)
    print(f"Nejrychlejší model: {fastest_model} ({format_latency(fastest['latency'])})")
    
    if test3_results.get("speedup"):
        print(f"Streaming speedup: {test3_results['speedup']:.1f}x rychlejsi na prvni token")
    
    # Calculate recommended timeout (2x average of successful responses)
    avg_latency = sum(r["latency"] for r in successful_models) / len(successful_models)
    recommended_timeout = int(avg_latency * 2)
    
    print(f"Doporuceny timeout: {recommended_timeout}s (prumer: {avg_latency:.1f}s)")
    print("=" * 50)


if __name__ == "__main__":
    main()
