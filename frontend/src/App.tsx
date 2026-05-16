import { useCallback, useRef, useState } from 'react'
import { Dashboard } from './components/Dashboard'
import { TranscriptFeed, type TranscriptTurn } from './components/TranscriptFeed'
import { VoiceButton, type VoiceServerMessage } from './components/VoiceButton'
import './App.css'

function App() {
  const [turns, setTurns] = useState<TranscriptTurn[]>([])
  const [voiceProcessing, setVoiceProcessing] = useState(false)
  const [pendingUserLine, setPendingUserLine] = useState('')
  const pendingUserRef = useRef('')

  const onVoiceMessage = useCallback((msg: VoiceServerMessage) => {
    if (msg.type === 'processing') {
      setVoiceProcessing(msg.active)
      return
    }
    if (msg.type === 'transcript') {
      pendingUserRef.current = msg.text
      setPendingUserLine(msg.text)
      return
    }
    if (msg.type === 'response') {
      const userLine = msg.user_transcript ?? pendingUserRef.current
      setTurns((prev) => [
        ...prev,
        { user: userLine, ai: msg.text },
      ])
      pendingUserRef.current = ''
      setPendingUserLine('')
      setVoiceProcessing(false)
      return
    }
    if (msg.type === 'error') {
      const userLine = msg.user_transcript ?? pendingUserRef.current
      setTurns((prev) => [
        ...prev,
        { user: userLine, ai: msg.text },
      ])
      pendingUserRef.current = ''
      setPendingUserLine('')
      setVoiceProcessing(false)
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
          <TranscriptFeed
            turns={turns}
            pendingUserText={pendingUserLine}
            assistantWorking={voiceProcessing}
          />
        </div>
        <div className="app-panel app-panel--dashboard">
          <Dashboard />
        </div>
      </div>
    </div>
  )
}

export default App
