# Mission — Kirana AI

## Problem

Kirana and SMB store owners track sales mentally or on paper. There is no real-time visibility into inventory levels or daily earnings without a dedicated POS system, which is too expensive and complex for most small stores.

## Solution

A voice-first operations layer. The owner speaks naturally to record a sale, check stock, or ask for today's earnings. The system handles transcription, intent detection, inventory updates, and responds via text-to-speech — no screen interaction required during a sale.

## Goals

- Voice → sale recorded → inventory decremented → TTS confirmation, in under 3 seconds
- React dashboard reflects live SQLite state (refreshes every 5 seconds)
- Low-stock alerts surfaced automatically after every sale
- Conversation history preserved across turns so references like "5 more of that" resolve correctly

## Non-Goals (Hackathon Scope)

- UPI QR generation per sale
- Multi-store / multi-user support
- Weekly or monthly analytics charts
- Production authentication or session management
- Payment processing

## Constraints

| Constraint | Detail |
|---|---|
| No external database | SQLite (`kirana.db`) + CSV (`conversations.csv`) only — stdlib, zero install |
| LLM API | Paytm Inference API — **text completion only, no tool/function calling** |
| Build window | 4 hours |
| Languages | English primary; Kannada intent keywords in regex (P1) |

## Definition of Done

All three demo commands work end-to-end:

1. *"Sold 2 packets of Parle-G and 1 Maggi"* → sale recorded, inventory decremented, TTS confirms total and any low-stock warning
2. *"How much did I make today?"* → TTS responds with revenue and transaction count from SQLite
3. *"What items are running low?"* → TTS lists low-stock products by name

After each command: `kirana.db` updated, `conversations.csv` appended, dashboard re-renders.
