# Roadmap — Kirana AI

Each phase is ~15–20 min and independently startable once its dependencies are done.
Phases 1–10 are backend; 11–14 are frontend; 15–16 are integration and ship.

---

## Backend

### Phase 1 — Scaffold
- Create directory tree: `backend/`, `frontend/`, `data/`, `specs/`
- Create `__init__.py` in every backend sub-package: `db/`, `logger/`, `parser/`, `tools/`, `agents/`, `voice/`
- `backend/requirements.txt`: `fastapi`, `uvicorn[standard]`, `pipecat-ai[sarvam]`, `python-dotenv`, `httpx`
- `.env.example` with all keys:
  ```
  SARVAM_API_KEY=          # STT (saaras:v3) + TTS (bulbul:v3)
  PAYTM_API_KEY=           # LLM text completion
  PAYTM_BASE_URL=          # e.g. https://api.paytm.com/v1  — confirm with Paytm docs
  PAYTM_MODEL=             # model name — confirm with Paytm docs
  VITE_BACKEND_URL=http://localhost:8000   # VITE_ prefix required — Vite only exposes vars with this prefix to the browser
  CORS_ORIGIN=http://localhost:5173        # set to Vercel URL in production
  ```
- `frontend/` Vite + React + TypeScript init (`npm create vite@latest frontend -- --template react-ts`)

### Phase 2 — SQLite schema (`db/database.py`)
- `get_conn()` with `row_factory` and WAL pragma
- `init_db()` — creates `inventory` + `sales` tables, then calls `_seed_inventory()` if table is empty
- `get_inventory()`, `get_product()`, `decrement_stock()`, `get_low_stock()`
- `insert_sale()`, `get_sales_summary(period)`
- Smoke test: `python -c "from db.database import init_db; init_db()"` → `data/kirana.db` created

#### Seed Inventory — 15 products (`_seed_inventory()`)

All prices in ₹. `stock_qty` is the starting stock. `low_stock_threshold` triggers the low-stock alert in TTS.

| # | `name` | `price` (₹) | `stock_qty` | `low_stock_threshold` | Category |
|---|---|---|---|---|---|
| 1 | Parle-G | 10 | 20 | 5 | Biscuits |
| 2 | Good Day Biscuit | 30 | 18 | 5 | Biscuits |
| 3 | Maggi Noodles | 14 | 15 | 5 | Instant food |
| 4 | Amul Butter | 55 | 8 | 3 | Dairy |
| 5 | Milk 500ml | 30 | 14 | 5 | Dairy |
| 6 | Amul Cheese Slice | 65 | 6 | 2 | Dairy |
| 7 | Tata Salt | 20 | 12 | 4 | Staples |
| 8 | Aashirvaad Atta 1kg | 60 | 10 | 3 | Staples |
| 9 | Fortune Sunflower Oil 1L | 180 | 6 | 2 | Staples |
| 10 | Lays Classic | 20 | 25 | 8 | Snacks |
| 11 | Kurkure Masala | 20 | 22 | 8 | Snacks |
| 12 | Colgate 100g | 55 | 10 | 3 | Personal care |
| 13 | Dettol Soap | 45 | 12 | 4 | Personal care |
| 14 | Clinic Plus Shampoo | 3 | 30 | 10 | Personal care |
| 15 | Thums Up 750ml | 45 | 18 | 5 | Beverages |

**Why this set:**
- Covers 6 categories so the dashboard inventory table looks realistic
- 3 items start near their threshold (`Amul Butter` at 8/3, `Fortune Oil` at 6/2, `Amul Cheese` at 6/2) — low-stock alert fires naturally after 1–2 demo sales without needing to exhaust stock first
- All names match common voice utterances: "Parle G", "Maggi", "Lays", "Thums Up" — no unusual spellings that would trip STT
- `Clinic Plus Shampoo` at ₹3/sachet is realistic for a kirana (single-use sachet pricing)

### Phase 3 — CSV logger (`logger/csv_logger.py`)
- `init_csv()` — creates `conversations.csv` with header if missing
- `log_turn(user_transcript, ai_response, detected_intent, session_id)`
- `get_recent_turns(session_id, n=5)` → list of dicts for history injection
- Smoke test: call `log_turn(...)` twice, open CSV and verify rows

### Phase 4 — Regex parser (`parser/regex_patterns.py`)
- `parse_transcript(text, product_names=[])` → `{intent, quantities, matched_items, dates, is_greeting, raw_text, timestamp}`
- Intent patterns (first match wins):

  | Intent | Trigger keywords |
  |---|---|
  | `greeting` | hello, hi, hey, good morning/afternoon/evening, namaste, vanakkam |
  | `record_sale` | sold, sell, sale, becha, diya |
  | `check_inventory` | stock, inventory, remaining, left, kitna hai, bacha |
  | `get_stats` | how much, total, earnings, revenue, made today, profit, kitna kamaya |
  | `unknown` | **none of the above matched** — guardrail L1 fires on this |

- **`unknown` is an explicit outcome**, not a fallback gap — any transcript that matches none of the above is classified as off-topic
- Include Hindi/Kannada keywords as listed above for `record_sale`, `check_inventory`, `get_stats`
- **Product name extraction** (used when `intent == 'record_sale'`):
  - Case-insensitive substring search for each name in `product_names` against `text`
  - `QUANTITY_PATTERN` finds `(amount, unit)` tuples with their string positions
  - Pair each product match with the nearest preceding quantity
  - Returns `matched_items: [{name, qty}]` — passed directly to `record_sale()` tool
- `product_names` list loaded once from SQLite at app startup and reused per turn
- Smoke tests:
  - `parse_transcript("Sold 2 packets of Parle-G and 1 Maggi", [...])` → `intent='record_sale'`, `matched_items=[{name:"Parle-G",qty:2},{name:"Maggi Noodles",qty:1}]`
  - `parse_transcript("What's the weather today?", [...])` → `intent='unknown'`
  - `parse_transcript("Tell me a joke", [...])` → `intent='unknown'`

### Phase 5 — Inventory tool (`tools/inventory.py`)
- `get_inventory()` → delegates to `db.get_inventory()`
- `get_low_stock()` → delegates to `db.get_low_stock()`
- `decrement_stock(product_name, quantity)` → delegates to `db.decrement_stock()`
- Returns structured dicts; raises `ValueError` for unknown products

### Phase 6 — Sales tool (`tools/sales.py`)
- `record_sale(items: list[dict])` — loops items, looks up price, calls `db.insert_sale()`, calls `db.decrement_stock()`, returns per-item result + total
- `get_today_sales()` → `db.get_sales_summary('today')`
- Uses `timestamp` column (not `created_at`) throughout — consistent with SQLite schema
- **Do not create `utils/filters.py`** — all date/period filtering is done in SQL inside `get_sales_summary()`; the Python-level filter utilities from the PRD are dead code

### Phase 7 — Kirana agent (`agents/kirana_agent.py`)
- `build_system_prompt(inventory_snapshot)` — persona + rules + inventory as plain text; includes **Layer 2 guardrail rules block** (see `tech-stack.md` Guardrails section)
- `build_context_block(parsed, tool_result)` — formats intent + `matched_items` + tool output as readable plain text (no JSON to LLM)
- `async def get_llm_response(transcript, parsed, tool_result, session_id)`:
  1. Fetch history via `csv_logger.get_recent_turns()`
  2. Build messages array (system + history + context block + user turn)
  3. POST to Paytm Inference API — **text completion, no tool schema** — using `httpx.AsyncClient`
  4. Return response text string
- `async def route_and_respond(transcript, session_id, product_names)`:
  1. `parsed = parse_transcript(transcript, product_names)`
  2. **[GUARDRAIL L1]** — check before any tool/LLM call:
     - `intent == 'unknown'` → `log_turn(intent='off_topic')`, return canned rejection string, **stop**
     - `intent == 'record_sale'` and `matched_items` empty → return "I couldn't identify the product…", **stop**
     - `intent == 'record_sale'` and any `qty <= 0` → return "That quantity doesn't seem right…", **stop**
  3. Route by `parsed['intent']`:
     - `greeting` → `tool_result = None` (no tool call) — LLM generates a friendly welcome response
     - `record_sale` → `tool_result = sales.record_sale(parsed['matched_items'])`
     - `get_stats` → `tool_result = sales.get_today_sales()`
     - `check_inventory` → `tool_result = inventory.get_low_stock()`
  4. Call `get_llm_response()` — system prompt contains **[GUARDRAIL L2]** rules
  5. Call `log_turn()` with actual `detected_intent`
  6. Return NL response string
- **Must be `async def`** — called from Pipecat's `AsyncFrameProcessor`, blocking will stall the pipeline
- Smoke tests:
  - `route_and_respond("What's the weather?", ...)` → returns canned rejection, CSV row has `detected_intent='off_topic'`
  - `route_and_respond("Sold 2 Parle-G", ...)` → tool runs, LLM responds, CSV row has `detected_intent='record_sale'`

### Phase 8 — Pipecat pipeline (`voice/pipeline.py`)
- `build_pipeline(websocket, product_names)` — assembles:
  `SarvamSTTService(model="saaras:v3")` → `KiranaFrameProcessor` → `SarvamTTSService(model="bulbul:v3", language="en-IN")`
- `KiranaFrameProcessor(AsyncFrameProcessor)`:
  - On `TranscriptionFrame` with non-empty text: `await route_and_respond(transcript, session_id, product_names)` → emit `TextFrame` with NL response; also emit `{"type":"transcript","text":...}` and `{"type":"response","text":...}` JSON frames over WebSocket
  - On empty transcript (VAD silence event): emit fallback `TextFrame("I didn't catch that, please try again.")` — no LLM call
- `session_id` = `uuid4()` generated once when WebSocket connects; passed through to `route_and_respond()` and `log_turn()`
- `run_pipeline(websocket)` — entry point; generates `session_id`, loads `product_names` from `db.get_inventory()`, calls `build_pipeline()`, runs until WebSocket closes
- Both services authenticated via `SARVAM_API_KEY` from env
- **Language note:** `en-IN` is default. To demo Kannada, change to `kn-IN` — do not hardcode `kn-IN` as it produces Kannada TTS for English text

### Phase 9 — FastAPI app (`main.py`)
- `lifespan` context: calls `init_db()` and `init_csv()` on startup
- Add `CORSMiddleware` with `allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")]` — **required or browser blocks all calls**; set `CORS_ORIGIN` to the Vercel URL in production env
- `GET /health` → `{"status": "ok"}`
- `WebSocket /ws/voice` → calls `run_pipeline(websocket)`, wraps in `try/finally` to handle disconnect without crashing (`WebSocketDisconnect` exception)

### Phase 10 — REST endpoints (add to `main.py`)
- `GET /api/dashboard` → `{sales: get_sales_summary('today'), inventory: get_inventory()}`
- `GET /api/sales?period=today` → `get_sales_summary(period)`
- `GET /api/inventory` → `get_inventory()`

---

## Frontend

### Phase 11 — VoiceButton (`frontend/src/components/VoiceButton.tsx`)
- Opens `WebSocket` to `ws://${import.meta.env.VITE_BACKEND_URL}/ws/voice` — note `VITE_` prefix
- On click: `getUserMedia({ audio: true })` → `AudioContext` at 16 kHz → `AudioWorklet` (`pcm-processor.js`) → sends raw `Int16Array` PCM chunks as binary WebSocket frames
  - **Must use AudioWorklet — `MediaRecorder` output (webm/opus) is rejected by Sarvam STT**
- Receives **text frames** (JSON) from backend: `{"type":"transcript"|"response"|"error","text":"..."}` — calls `onMessage(msg)` callback prop
- Receives **binary frames** from backend: TTS audio PCM chunks from Pipecat — feed into a playback `AudioContext` via `AudioBufferSourceNode` and play immediately
  - Create a second `AudioContext` (output) at the sample rate Sarvam TTS emits (typically 22050 Hz); decode each binary chunk and queue for gapless playback
- Handles `NotAllowedError` on `getUserMedia` → shows inline "Microphone access needed" UI
- Handles WebSocket `close`/`error` → stop mic, re-enable button, show status

### Phase 12 — Dashboard (`frontend/src/components/Dashboard.tsx`)
- Fetches `GET /api/dashboard` immediately on mount, then re-fetches every 5 seconds via `setInterval`
- Renders: today's total (₹), transaction count, inventory table (name / stock / status chip: OK / Low / Out)
- Status chip: `stock_qty === 0` → Out, `stock_qty <= low_stock_threshold` → Low, else OK

### Phase 13 — TranscriptFeed (`frontend/src/components/TranscriptFeed.tsx`)
- Receives `{user, ai}` turn objects via prop
- Renders scrollable list, newest at bottom
- Auto-scrolls on new entry

### Phase 14 — App wiring (`frontend/src/App.tsx`)
- Composes `VoiceButton` + `TranscriptFeed` + `Dashboard`
- Manages `turns: {user: string, ai: string}[]` state for transcript feed
- `onMessage` callback from `VoiceButton`:
  - `type === 'transcript'` → buffer the user text in a `pendingTranscript` ref
  - `type === 'response'` → pair with buffered transcript, push `{user: pendingTranscript, ai: text}` into `turns`, clear buffer
  - `type === 'error'` → push `{user: pendingTranscript, ai: text}` and clear buffer
- Passes `turns` to `TranscriptFeed`
- Single route `/` for demo (no router needed)

---

## Integration & Ship

### Phase 15 — E2E smoke test
- Start backend: `cd backend && uvicorn main:app --reload` (must run from inside `backend/`)
- Start frontend: `cd frontend && npm run dev`
- Run 3 demo commands via browser mic; verify:
  - `data/kirana.db` stock decremented after sale
  - `data/conversations.csv` has new row
  - Dashboard updates within 5 seconds
  - TTS plays correct response

### Phase 16 — Polish + deploy
- Clean up UI (font, spacing, status colours)
- Set env vars on Railway (backend):
  - `SARVAM_API_KEY`, `PAYTM_API_KEY`, `PAYTM_BASE_URL`, `PAYTM_MODEL`
  - `CORS_ORIGIN=https://<your-app>.vercel.app`
  - **Railway sets `PORT` dynamically** — start command must be `uvicorn main:app --host 0.0.0.0 --port $PORT`, not a hardcoded port
- Set env vars on Vercel (frontend):
  - `VITE_BACKEND_URL=https://<your-app>.railway.app`
- Deploy; confirm `/health` returns 200
- Run demo script one final time on production URL
