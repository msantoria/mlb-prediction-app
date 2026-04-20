import React, { useState } from 'react'

const API = import.meta.env.VITE_API_BASE_URL || ''

export default function AIPage() {
  const [question, setQuestion] = useState('How many matchups are there today?')
  const [response, setResponse] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function ask() {
    setLoading(true)
    setError(null)

    try {
      const res = await fetch(`${API}/ai/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })

      if (!res.ok) {
        const text = await res.text()
        throw new Error(text || `Request failed (${res.status})`)
      }

      const json = await res.json()
      setResponse(json)

    } catch (err) {
      console.error('AI request failed:', err)
      setError(err.message || 'Request failed')
      setResponse(null)

    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: '24px', marginBottom: '12px' }}>AI Data Assistant</h1>
      <p style={{ color: '#8b949e', marginBottom: '12px' }}>
        Ask about matchups by day, weather, and team performance (e.g. "team 147").
      </p>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '14px' }}>
        <input
          value={question}
          onChange={e => setQuestion(e.target.value)}
          style={{
            flex: 1,
            background: '#161b22',
            color: '#e6edf3',
            border: '1px solid #30363d',
            borderRadius: '6px',
            padding: '10px'
          }}
        />

        <button onClick={ask} disabled={loading}>
          {loading ? 'Asking…' : 'Ask'}
        </button>
      </div>

      {error && (
        <div style={{
          background: '#2d1b1b',
          border: '1px solid #a33',
          borderRadius: '8px',
          padding: '14px',
          marginBottom: '12px'
        }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {response && (
        <div style={{
          background: '#161b22',
          border: '1px solid #30363d',
          borderRadius: '8px',
          padding: '14px'
        }}>

          <div style={{ fontWeight: 700, marginBottom: '8px' }}>
            Answer
          </div>

          <div style={{ marginBottom: '10px' }}>
            {response.answer}
          </div>

          {response.sources?.length > 0 && (
            <div style={{ fontSize: '12px', color: '#8b949e' }}>
              Sources: {response.sources.join(', ')}
            </div>
          )}

          {response.data && (
            <pre style={{
              marginTop: '12px',
              background: '#0d1117',
              borderRadius: '6px',
              padding: '10px',
              overflowX: 'auto',
              fontSize: '12px'
            }}>
              {JSON.stringify(response.data, null, 2)}
            </pre>
          )}

        </div>
      )}

    </div>
  )
}
