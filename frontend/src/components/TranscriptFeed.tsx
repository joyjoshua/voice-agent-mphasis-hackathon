import { useEffect, useRef } from 'react'
import './TranscriptFeed.css'

export type TranscriptTurn = {
  user: string
  ai: string
}

export type TranscriptFeedProps = {
  turns: TranscriptTurn[]
}

export function TranscriptFeed({ turns }: TranscriptFeedProps) {
  const anchorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    anchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  return (
    <section
      className="transcript-feed"
      aria-label="Conversation transcript"
    >
      <h2 className="transcript-feed-header">Transcript</h2>
      <div className="transcript-feed-scroll">
        {turns.length === 0 ? (
          <p className="transcript-feed-empty">
            Voice replies will appear here after you speak.
          </p>
        ) : (
          <ul className="transcript-feed-list">
            {turns.map((turn, index) => (
              <li key={`turn-${index}`}>
                <article className="transcript-turn transcript-turn--you">
                  <span className="transcript-turn-label">You</span>
                  <p className="transcript-turn-text">
                    {turn.user || '(empty)'}
                  </p>
                </article>
                <article className="transcript-turn transcript-turn--assistant">
                  <span className="transcript-turn-label">Assistant</span>
                  <p className="transcript-turn-text">{turn.ai}</p>
                </article>
              </li>
            ))}
          </ul>
        )}
        <div ref={anchorRef} className="transcript-feed-anchor" aria-hidden />
      </div>
    </section>
  )
}
