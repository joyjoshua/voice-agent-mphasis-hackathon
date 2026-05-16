import { useCallback, useRef, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { TranscriptFeed, type TranscriptTurn } from './components/TranscriptFeed'
import { VoiceButton, type VoiceServerMessage } from './components/VoiceButton'
import './App.css'

function App() {
  const [turns, setTurns] = useState<TranscriptTurn[]>([])
  const pendingTranscript = useRef('')

  const onVoiceMessage = useCallback((msg: VoiceServerMessage) => {
    if (msg.type === 'transcript') {
      pendingTranscript.current = msg.text
      return
    }
    if (msg.type === 'response') {
      setTurns((prev) => [
        ...prev,
        { user: pendingTranscript.current, ai: msg.text },
      ])
      pendingTranscript.current = ''
      return
    }
    if (msg.type === 'error') {
      setTurns((prev) => [
        ...prev,
        { user: pendingTranscript.current, ai: msg.text },
      ])
      pendingTranscript.current = ''
    }
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <h1>Kirana AI</h1>
        <p className="app-tagline">
          Voice assistant for sales, stock, and today&apos;s earnings
        </p>
      </header>

      <div className="app-grid">
        <div className="app-panel app-panel--voice">
          <VoiceButton onMessage={onVoiceMessage} />
        </div>
        <div className="app-panel app-panel--transcript">
          <TranscriptFeed turns={turns} />
        </div>
        <div className="app-panel app-panel--dashboard">
          <Dashboard />
        </div>
      </div>
    </div>
  )
}

export default App
