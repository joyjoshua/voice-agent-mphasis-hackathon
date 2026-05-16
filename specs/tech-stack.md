# Tech Stack — Kirana AI

## Layer Overview

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React + TypeScript (Vite) | |
| Backend | Python 3.11 + FastAPI | Uvicorn server |
| Voice pipeline | Pipecat | WebSocket transport |
| STT | Sarvam AI `saaras:v3` | Streaming WebSocket, VAD built-in, 22 Indian languages |
| LLM | Paytm Inference API | Text completion only — see constraint below |
| TTS | Sarvam AI `bulbul:v3` | WebSocket streaming, 35+ voices, Kannada/Hindi/English |
| Intent routing | `parser/regex_patterns.py` | Runs before LLM, not inside it |
| Storage | SQLite + CSV | `sqlite3` + `csv` from Python stdlib |
| Deployment | Vercel (frontend) + Railway (backend) | |

---

## Critical Constraint: No LLM Tool Calling

The Paytm Inference API does **not** support tool/function calling. The PRD's original architecture (LLM dispatches tool calls) is not viable.

**Canonical interaction model:**

```
Mic → STT (Sarvam saaras:v3)
        ↓
  parse_transcript()        ← regex extracts intent, quantities, dates
        ↓
  ┌─ [GUARDRAIL L1] ────────────────────────────────────────────────┐
  │  intent == 'unknown'?                                            │
  │  → canned rejection → TTS → log(intent='off_topic') → STOP     │
  └──────────────────────────────────────────────────────────────────┘
        ↓ (known intent passes through)
  intent router             ← Python if/elif, not LLM
        ↓
  tool executes             ← record_sale() / get_sales_summary() / get_low_stock()
        ↓
  build_prompt()            ← system prompt (with L2 guardrail rules) + history + tool result
        ↓
  ┌─ [GUARDRAIL L2] ────────────────────────────────────────────────┐
  │  System prompt rules block off-topic responses from LLM          │
  │  (catches edge cases that pass regex but are still off-topic)    │
  └──────────────────────────────────────────────────────────────────┘
        ↓
  Paytm LLM API             ← generates natural language response ONLY
        ↓
  TTS (Sarvam bulbul:v3 — speaks response)
        ↓
  log_turn() → CSV
```

The LLM's only job is to turn structured data (tool output) into a natural spoken sentence. It does not decide which tool to run.

---

## Guardrails

### Layer 1 — Regex intent filter (in `route_and_respond()`)

Fires before any LLM call. Cost: zero tokens.

| Condition | Action |
|---|---|
| `intent == 'unknown'` | Return canned response immediately, log `detected_intent='off_topic'`, skip tool + LLM |
| `intent == 'record_sale'` and `matched_items` is empty | Return "I couldn't identify the product. Try saying the item name clearly." — skip tool |
| `intent == 'record_sale'` and any `qty <= 0` | Return "That quantity doesn't seem right — can you repeat?" — skip tool |

**Canned rejection text** (TTS-safe, no markdown):
> "I'm your store assistant. I can help with sales, inventory, and today's earnings. Try saying: sold 2 Parle-G, how much did I make today, or what's running low."

### Layer 2 — System prompt guardrail (in `build_system_prompt()`)

Added as a mandatory rules block inside the system prompt. Fires inside the LLM for inputs that pass regex intent detection but drift off-topic within the conversation.

```
STRICT RULES — never break these:
- You only answer questions about: recording sales, checking stock levels, and store earnings.
- If asked about anything else (weather, news, sports, personal advice, general knowledge, coding):
  respond exactly: "I'm your store assistant. Ask me about sales, stock, or today's earnings."
- Never provide general knowledge, opinions, or answers outside the store domain.
- Never make up product prices or stock levels — only use the tool result provided to you.
- Keep all responses under 2 sentences. This is voice — no lists, no markdown.
```

---

## Entity Extraction Strategy

**Problem:** Regex detects intent (`record_sale`) but not *what* was sold. "Sold 2 Parle-G and 1 Maggi" needs both product names and quantities.

**Solution: inventory-aware fuzzy match in `parse_transcript()`**

Since the seeded inventory has only 15 known products, `parse_transcript()` accepts the product name list and matches them against the transcript via case-insensitive substring search, then pairs each match with the nearest preceding quantity:

```
transcript: "Sold 2 packets of Parle-G and 1 Maggi"
inventory:  ["Parle-G", "Maggi Noodles", "Amul Butter", ...]

→ matched products: ["Parle-G" at pos 18, "Maggi" at pos 32]
→ QUANTITY_PATTERN finds: [("2", "packets") at pos 5, ("1", None) at pos 27]
→ pair by proximity: [{name: "Parle-G", qty: 2}, {name: "Maggi Noodles", qty: 1}]
```

`parse_transcript(text, product_names=[])` — product list loaded from SQLite once on startup and passed in. For `check_inventory` / `get_stats`, product name extraction is optional (single product lookup only).

This is deterministic, zero-latency, and sufficient for the 15-product demo. No second LLM call needed for entity extraction.

---

## Sarvam AI Voice Models

| Role | Model | Pipecat service class | Notes |
|---|---|---|---|
| STT | `saaras:v3` | `pipecat.services.sarvam.stt.SarvamSTTService` | Streaming WebSocket, VAD + silence detection built-in, 22 Indian languages |
| TTS | `bulbul:v3` | `pipecat.services.sarvam.tts.SarvamTTSService` | WebSocket streaming, SENTENCE aggregation mode for natural prosody |

**Why these models:**
- `saaras:v3` is Sarvam's most accurate STT; handles code-mixed speech (e.g., "Sold 2 packets of Parle-G") and Kannada natively
- `bulbul:v3` is the latest GA TTS release (35+ voices, kn-IN + hi-IN + en-IN); `bulbul:v3-beta` exists but v3 is production-stable
- Both have first-class Pipecat service classes — no custom wrappers needed

**Single API key** (`SARVAM_API_KEY`) covers both STT and TTS.

**Audio format:** Sarvam STT WebSocket accepts only `pcm_s16le` (16-bit signed PCM, 16 kHz, mono). The browser `VoiceButton` component must use an `AudioWorklet` to capture and send raw PCM — `MediaRecorder` output (webm/opus) is not accepted.

**TTS language:** Default `en-IN` (English). Switch to `kn-IN` for Kannada demo (P1). Do not hardcode `kn-IN` as default — English is primary for the hackathon demo.

---

## WebSocket Message Protocol (`/ws/voice`)

All messages between frontend and backend are JSON:

```jsonc
// Backend → Frontend
{"type": "transcript", "text": "Sold 2 packets of Parle-G"}   // STT result
{"type": "response",   "text": "Sale recorded. Total ₹38..."}  // AI response
{"type": "error",      "text": "I didn't catch that..."}       // fallback
```

Frontend sends: binary audio frames (PCM chunks from AudioWorklet).

---

## LLM Prompt Structure (per turn)

```
[System]
You are Kirana AI... (persona, rules, current inventory snapshot as plain text)

[History — last 5 turns from conversations.csv]
User: ...
Assistant: ...

[Context block — plain text, NOT JSON to LLM]
Intent detected: record_sale
Items parsed: Parle-G x2, Maggi x1
Tool result: Sale recorded. Total ₹38. Parle-G now has 3 units remaining (LOW STOCK).

[Current turn]
User: Sold 2 packets of Parle-G and 1 Maggi
```

---

## Data Storage

### SQLite — `data/kirana.db`

- Tables: `inventory`, `sales`
- Auto-created + seeded by `init_db()` on FastAPI startup
- WAL mode enabled for safe concurrent writes

### CSV — `data/conversations.csv`

- Columns: `timestamp`, `user_transcript`, `ai_response`, `detected_intent`, `session_id`
- Append-only; `init_csv()` creates with header if missing
- Last 5 rows per session injected as LLM conversation history

---

## API Surface

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `WebSocket` | `/ws/voice` | Pipecat pipeline connection |
| `GET` | `/api/dashboard` | Today's sales summary + full inventory |
| `GET` | `/api/sales` | Sales stats (`?period=today\|this_week\|this_month`) |
| `GET` | `/api/inventory` | All products + stock levels |
