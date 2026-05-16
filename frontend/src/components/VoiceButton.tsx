import { useCallback, useRef, useState } from 'react'
import './VoiceButton.css'

/** Matches backend `voice/pipeline.py` Sarvam bulbul:v3 output (`linear16`). */
const PLAYBACK_SAMPLE_RATE_HZ = 24000

export type VoiceServerMessage =
  | { type: 'transcript'; text: string }
  | { type: 'response'; text: string; user_transcript?: string }
  | { type: 'error'; text: string; user_transcript?: string }
  | { type: 'processing'; active: boolean }

export type VoiceButtonProps = {
  onMessage: (msg: VoiceServerMessage) => void
}

function voiceWebSocketUrl(): string {
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${scheme}//${window.location.host}/ws/voice`
  }
  const raw = import.meta.env.VITE_BACKEND_URL ?? ''
  const normalized = raw.startsWith('http') ? raw : `http://${raw}`
  let hostPath: string
  try {
    hostPath = new URL(normalized).host
  } catch {
    hostPath = 'localhost:8000'
  }
  const secure =
    typeof window !== 'undefined' && window.location.protocol === 'https:'
  const scheme = secure ? 'wss' : 'ws'
  return `${scheme}://${hostPath}/ws/voice`
}

export function VoiceButton({ onMessage }: VoiceButtonProps) {
  const [live, setLive] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [status, setStatus] = useState<string>('Idle — click to talk')
  const [micDenied, setMicDenied] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const micCtxRef = useRef<AudioContext | null>(null)
  const playCtxRef = useRef<AudioContext | null>(null)
  const workletRef = useRef<AudioWorkletNode | null>(null)
  const micSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const nextPlayTimeRef = useRef<number>(0)

  const stopAll = useCallback(
    (reason?: string) => {
      const ws = wsRef.current
      wsRef.current = null
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(1000, 'client-stop')
      }

      workletRef.current?.disconnect()
      workletRef.current = null
      micSourceRef.current?.disconnect()
      micSourceRef.current = null

      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null

      void micCtxRef.current?.close().catch(() => {})
      micCtxRef.current = null

      void playCtxRef.current?.close().catch(() => {})
      playCtxRef.current = null
      nextPlayTimeRef.current = 0

      setLive(false)
      if (reason) setStatus(reason)
    },
    [],
  )

  const enqueuePlayback = useCallback((pcmBuffer: ArrayBuffer) => {
    const ctx = playCtxRef.current
    if (!ctx) return

    const samples = pcmBuffer.byteLength / 2
    if (samples <= 0) return

    const i16 = new Int16Array(pcmBuffer)
    const f32 = new Float32Array(samples)
    for (let i = 0; i < samples; i++) {
      f32[i] = i16[i]! / 32768
    }

    const audioBuf = ctx.createBuffer(1, samples, PLAYBACK_SAMPLE_RATE_HZ)
    audioBuf.copyToChannel(f32, 0)

    const src = ctx.createBufferSource()
    src.buffer = audioBuf
    src.connect(ctx.destination)

    const now = ctx.currentTime
    const startAt = Math.max(nextPlayTimeRef.current, now + 0.02)
    src.start(startAt)
    nextPlayTimeRef.current = startAt + audioBuf.duration
  }, [])

  const startSession = useCallback(async () => {
    setMicDenied(false)
    setConnecting(true)
    setStatus('Connecting…')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: false,
      })
      streamRef.current = stream

      const ws = new WebSocket(voiceWebSocketUrl())
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.onmessage = (ev: MessageEvent<ArrayBuffer | string | Blob>) => {
        if (typeof ev.data === 'string') {
          try {
            const parsed: unknown = JSON.parse(ev.data)
            if (parsed && typeof parsed === 'object' && 'type' in parsed) {
              const t = (parsed as { type: unknown }).type
              if (t === 'processing' && 'active' in parsed) {
                const active = (parsed as { active: unknown }).active
                if (typeof active === 'boolean') {
                  onMessage({ type: 'processing', active })
                }
              } else if (t === 'transcript' && 'text' in parsed) {
                const tx = (parsed as { text: unknown }).text
                if (typeof tx === 'string') {
                  onMessage({ type: 'transcript', text: tx })
                }
              } else if (t === 'response' && 'text' in parsed) {
                const tx = (parsed as { text: unknown }).text
                if (typeof tx === 'string') {
                  const ut = (parsed as { user_transcript?: unknown }).user_transcript
                  onMessage({
                    type: 'response',
                    text: tx,
                    user_transcript:
                      typeof ut === 'string' ? ut : undefined,
                  })
                }
              } else if (t === 'error' && 'text' in parsed) {
                const tx = (parsed as { text: unknown }).text
                if (typeof tx === 'string') {
                  const ut = (parsed as { user_transcript?: unknown }).user_transcript
                  onMessage({
                    type: 'error',
                    text: tx,
                    user_transcript:
                      typeof ut === 'string' ? ut : undefined,
                  })
                }
              }
            }
          } catch {
            /* ignore non-JSON */
          }
          return
        }
        if (ev.data instanceof ArrayBuffer) {
          enqueuePlayback(ev.data)
          return
        }
        if (ev.data instanceof Blob) {
          void ev.data.arrayBuffer().then((buf) => enqueuePlayback(buf))
        }
      }

      ws.onclose = () => {
        stopAll()
        setStatus((prev) =>
          prev.startsWith('Stopped') ? prev : 'Disconnected — click to talk again',
        )
      }

      await new Promise<void>((resolve, reject) => {
        const fail = () => reject(new Error('WebSocket failed'))
        ws.addEventListener('open', () => resolve(), { once: true })
        ws.addEventListener('error', fail, { once: true })
      })

      ws.onerror = () => {
        setStatus('Voice connection error — session ended')
        stopAll()
      }

      const micCtx = new AudioContext({ sampleRate: 16000 })
      micCtxRef.current = micCtx

      const playCtx = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE_HZ })
      playCtxRef.current = playCtx
      nextPlayTimeRef.current = playCtx.currentTime

      const workletUrl = new URL('/pcm-processor.js', window.location.origin).href
      await micCtx.audioWorklet.addModule(workletUrl)

      const workletNode = new AudioWorkletNode(micCtx, 'pcm-processor')
      workletRef.current = workletNode

      workletNode.port.onmessage = (ev: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN && ev.data?.byteLength) {
          ws.send(ev.data)
        }
      }

      const micSrc = micCtx.createMediaStreamSource(stream)
      micSourceRef.current = micSrc
      micSrc.connect(workletNode)

      setLive(true)
      setStatus(
        micCtx.sampleRate === 16000
          ? 'Listening (16 kHz mic)'
          : `Listening (mic ${Math.round(micCtx.sampleRate)} Hz → 16 kHz PCM)`,
      )
    } catch (err: unknown) {
      stopAll()
      const name =
        err && typeof err === 'object' && 'name' in err
          ? String((err as DOMException).name)
          : ''
      if (name === 'NotAllowedError') {
        setMicDenied(true)
        setStatus('Microphone blocked — allow access to use voice')
        return
      }
      setStatus('Could not start voice session — try again')
    } finally {
      setConnecting(false)
    }
  }, [enqueuePlayback, onMessage, stopAll])

  const toggle = useCallback(() => {
    if (live) {
      stopAll('Stopped — click to talk again')
      return
    }
    void startSession()
  }, [live, startSession, stopAll])

  const statusClass =
    micDenied || status.includes('error')
      ? 'voice-button-status voice-button-status--error'
      : status.includes('blocked')
        ? 'voice-button-status voice-button-status--warn'
        : 'voice-button-status'

  return (
    <div className="voice-button-wrap">
      <button
        type="button"
        className={
          live ? 'voice-button voice-button--live' : 'voice-button'
        }
        onClick={toggle}
        disabled={connecting}
      >
        {connecting
          ? 'Connecting…'
          : live
            ? 'Stop voice'
            : 'Start voice'}
      </button>
      <p className={statusClass}>{status}</p>
      {micDenied ? (
        <p className="voice-button-status voice-button-status--warn">
          Microphone access needed — check browser permissions for this site.
        </p>
      ) : null}
    </div>
  )
}
