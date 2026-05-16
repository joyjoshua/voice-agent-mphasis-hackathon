import { useEffect, useRef } from 'react'
import './TranscriptFeed.css'

export type TranscriptTurn = {
  user: string
  ai: string
}

export type TranscriptFeedProps = {
  turns: TranscriptTurn[]
  /** Latest STT line while waiting for the assistant reply */
  pendingUserText?: string
  /** True while NLU / routing runs (after transcript, before response) */
  assistantWorking?: boolean
}

export function TranscriptFeed({
  turns,
  pendingUserText = '',
  assistantWorking = false,
}: TranscriptFeedProps) {
  const anchorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    anchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, pendingUserText, assistantWorking])

  const showLiveTurn = assistantWorking || pendingUserText.length > 0

  const listEmpty = turns.length === 0 && !showLiveTurn

  return (
    <section
      className="transcript-feed"
      aria-label="Conversation transcript"
    >
      <h2 className="transcript-feed-header">Transcript</h2>
      <div className="transcript-feed-scroll">
        {listEmpty ? (
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
            {showLiveTurn ? (
              <li key="live">
                <article className="transcript-turn transcript-turn--you">
                  <span className="transcript-turn-label">You</span>
                  <p className="transcript-turn-text">
                    {pendingUserText || (assistantWorking ? '…' : '(empty)')}
                  </p>
                </article>
                <article
                  className={
                    assistantWorking
                      ? 'transcript-turn transcript-turn--assistant transcript-turn--pending'
                      : 'transcript-turn transcript-turn--assistant'
                  }
                >
                  <span className="transcript-turn-label">Assistant</span>
                  <p className="transcript-turn-text transcript-turn-text--pending">
                    {assistantWorking ? (
                      <>
                        <span className="transcript-thinking" aria-hidden>
                          ●
                        </span>{' '}
                        Thinking…
                      </>
                    ) : (
                      '…'
                    )}
                  </p>
                </article>
              </li>
            ) : null}
          </ul>
        )}
        <div ref={anchorRef} className="transcript-feed-anchor" aria-hidden />
      </div>
    </section>
  )
}
