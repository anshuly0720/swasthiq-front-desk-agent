"""Which models will this key actually serve? One real call each."""

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ.get("LLM_API_KEY", "").strip()
BASE = "https://generativelanguage.googleapis.com/v1beta"

CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
]

for name in CANDIDATES:
    try:
        reply = httpx.post(
            "{}/models/{}:generateContent".format(BASE, name),
            params={"key": KEY},
            json={
                "contents": [{"parts": [{"text": "Return JSON: {\"ok\": true}"}]}],
                "generationConfig": {"temperature": 0,
                                     "responseMimeType": "application/json"},
            },
            timeout=60,
        )
    except httpx.HTTPError as error:
        print(name.ljust(26), "TRANSPORT", error)
        continue

    if reply.status_code == 200:
        usage = reply.json().get("usageMetadata", {})
        print(name.ljust(26), "200  OK   tokens:", usage.get("totalTokenCount"))
    else:
        detail = reply.json().get("error", {})
        print(name.ljust(26), reply.status_code, detail.get("status"),
              "|", (detail.get("message") or "")[:150])
    time.sleep(2)