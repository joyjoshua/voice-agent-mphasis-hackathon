"""Pipecat voice pipeline: Sarvam STT → Kirana NLU → Sarvam TTS over FastAPI WebSocket.

JSON frames to the frontend (same socket as binary audio):
  { "type": "processing", "active": bool } — thinking / routing indicator
  { "type": "transcript", "text": str }   — STT line (shown in transcript)
  { "type": "response",  "text": str }   — assistant reply (voice + chat)
  { "type": "error",      "text": str }  — error line for chat + TTS
"""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import WebSocket
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from starlette.websockets import WebSocketState

from agents.kirana_agent import route_and_respond
from db.database import get_inventory

load_dotenv()

_MIC_SAMPLE_RATE_HZ = 16000
_TTS_OUT_SAMPLE_RATE_HZ = 24000  # bulbul:v3 default (see SarvamTTSService docs)
_FALLBACK_NO_UTTERANCE = "I didn't catch that, please try again."
_EMPTY_TRANSCRIPT_GUARD_SEC = 1.0


class KiranaPCMWebsocketSerializer(FrameSerializer):
    """Binary mic PCM16 mono @16 kHz in; TTS PCM bytes out (matches frontend roadmap)."""

    async def setup(self, frame: StartFrame):
        pass

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, str):
            return None
        if not data:
            return None
        return InputAudioRawFrame(
            audio=data,
            sample_rate=_MIC_SAMPLE_RATE_HZ,
            num_channels=1,
        )

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None


class TranscriptForwarder(FrameProcessor):
    """After STT: notify UI (processing + transcript) before routing/TTS work (cf. cashflow-whisperer)."""

    def __init__(self, *, websocket: WebSocket, **kwargs) -> None:
        super().__init__(**kwargs)
        self._websocket = websocket

    async def _safe_send_json(self, payload: dict) -> None:
        try:
            if self._websocket.application_state == WebSocketState.DISCONNECTED:
                return
            await self._websocket.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, TranscriptionFrame):
            await self._safe_send_json({"type": "processing", "active": True})
            raw = frame.text or ""
            await self._safe_send_json({"type": "transcript", "text": raw.strip()})
        await self.push_frame(frame, direction)


class KiranaVoiceProcessor(FrameProcessor):
    """Routes transcripts to `route_and_respond`; TTS + clears `processing` when done."""

    def __init__(
        self,
        *,
        websocket: WebSocket,
        session_id: str,
        product_names: list[str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._websocket = websocket
        self._session_id = session_id
        self._product_names = product_names
        self._segment_id = 0
        self._got_transcript_for_segment = False

    async def _safe_send_json(self, payload: dict) -> None:
        try:
            if self._websocket.application_state == WebSocketState.DISCONNECTED:
                return
            await self._websocket.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    async def _send_processing(self, active: bool) -> None:
        await self._safe_send_json({"type": "processing", "active": active})

    async def _emit_fallback_reply(self, *, processing_already_on: bool) -> None:
        """STT silence / empty transcript: TTS-only fallback, no LLM."""
        if not processing_already_on:
            await self._send_processing(True)
        await self._safe_send_json({"type": "transcript", "text": ""})
        await self._safe_send_json(
            {"type": "response", "text": _FALLBACK_NO_UTTERANCE, "user_transcript": ""}
        )
        await self.push_frame(TextFrame(_FALLBACK_NO_UTTERANCE))
        await self._send_processing(False)

    async def _empty_transcript_guard(self, utterance_id: int) -> None:
        await asyncio.sleep(_EMPTY_TRANSCRIPT_GUARD_SEC)
        if utterance_id != self._segment_id:
            return
        if self._got_transcript_for_segment:
            return
        await self._emit_fallback_reply(processing_already_on=False)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStartedSpeakingFrame):
            self._segment_id += 1
            self._got_transcript_for_segment = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            utterance_id = self._segment_id
            self.create_task(self._empty_transcript_guard(utterance_id))
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            self._got_transcript_for_segment = True
            if not text:
                await self._emit_fallback_reply(processing_already_on=True)
                return

            try:
                reply = await route_and_respond(text, self._session_id, self._product_names)
            except Exception:
                err_text = "Something went wrong. Please try again."
                await self._safe_send_json(
                    {"type": "error", "text": err_text, "user_transcript": text}
                )
                await self.push_frame(TextFrame(err_text))
            else:
                await self._safe_send_json(
                    {"type": "response", "text": reply, "user_transcript": text}
                )
                await self.push_frame(TextFrame(reply))
            finally:
                await self._send_processing(False)
            return

        await self.push_frame(frame, direction)


def build_pipeline(
    websocket: WebSocket,
    product_names: list[str],
    session_id: str,
) -> PipelineTask:
    """Assemble STT → TranscriptForwarder → KiranaVoiceProcessor → TTS (+ transport)."""
    api_key = (os.getenv("SARVAM_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("SARVAM_API_KEY is not set")

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=_MIC_SAMPLE_RATE_HZ,
            audio_out_sample_rate=_TTS_OUT_SAMPLE_RATE_HZ,
            serializer=KiranaPCMWebsocketSerializer(),
            add_wav_header=False,
        ),
    )

    # Sarvam streaming SDK (sarvamai) validates AudioData.encoding as audio/wav only.
    # Use input_audio_codec="wav" so raw mic PCM can be sent; pcm_s16le is rejected by the client.
    stt = SarvamSTTService(
        api_key=api_key,
        model="saaras:v3",
        sample_rate=_MIC_SAMPLE_RATE_HZ,
        audio_passthrough=False,
        input_audio_codec="wav",
        mode="codemix",
    )

    transcript_forwarder = TranscriptForwarder(websocket=websocket, name="TranscriptForwarder")
    kirana_voice = KiranaVoiceProcessor(
        websocket=websocket,
        session_id=session_id,
        product_names=product_names,
        name="KiranaVoiceProcessor",
    )

    tts = SarvamTTSService(
        api_key=api_key,
        model="bulbul:v3",
        sample_rate=_TTS_OUT_SAMPLE_RATE_HZ,
        settings=SarvamTTSService.Settings(
            language="en-IN",
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_forwarder,
            kirana_voice,
            tts,
            transport.output(),
        ]
    )

    return PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=_MIC_SAMPLE_RATE_HZ,
            audio_out_sample_rate=_TTS_OUT_SAMPLE_RATE_HZ,
            allow_interruptions=False,
        ),
        cancel_on_idle_timeout=False,
        enable_rtvi=False,
        idle_timeout_secs=None,
        enable_turn_tracking=False,
    )


async def run_pipeline(websocket: WebSocket) -> None:
    """One browser voice session: fresh `session_id`, inventory names, run until disconnect."""
    session_id = str(uuid4())
    rows = get_inventory()
    product_names = [str(r["name"]) for r in rows]

    task = build_pipeline(websocket, product_names, session_id)
    runner = PipelineRunner(handle_sigint=False, handle_sigterm=False)
    await runner.run(task)
