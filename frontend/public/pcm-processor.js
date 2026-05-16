/**
 * Captures mono microphone Float32 from the AudioContext and emits Int16 PCM @16 kHz
 * as transferable ArrayBuffers (binary chunks for Sarvam STT).
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this._targetHz = 16000
    this._frameSamples = 320 // ~20 ms @16 kHz
    this._pcm = new Int16Array(this._frameSamples)
    this._pcmIdx = 0
    this._ratio = this._targetHz / sampleRate
    this._acc = 0
  }

  _toInt16(v) {
    v = Math.max(-1, Math.min(1, v))
    return (v < 0 ? v * 0x8000 : v * 0x7fff) | 0
  }

  _flushIfFull() {
    if (this._pcmIdx < this._frameSamples) return
    this.port.postMessage(this._pcm.buffer, [this._pcm.buffer])
    this._pcm = new Int16Array(this._frameSamples)
    this._pcmIdx = 0
  }

  process(inputs) {
    const ch0 = inputs[0]?.[0]
    if (!ch0?.length) return true

    for (let i = 0; i < ch0.length; i++) {
      const s = ch0[i]
      this._acc += this._ratio
      while (this._acc >= 1) {
        this._acc -= 1
        this._pcm[this._pcmIdx++] = this._toInt16(s)
        this._flushIfFull()
      }
    }
    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
