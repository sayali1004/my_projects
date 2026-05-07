import { useState, useEffect, useRef } from 'react'
import { Send, Database, Bot, User } from 'lucide-react'
import { streamMessage, getMessages } from '../api'

export default function ChatWindow({ chat, project, onChatCreated }) {
  const [messages, setMessages]   = useState([])
  const [input, setInput]         = useState('')
  const [loading, setLoading]     = useState(false)
  const bottomRef                  = useRef(null)

  useEffect(() => {
    if (chat?.id) loadMessages(chat.id)
    else setMessages([])
  }, [chat?.id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadMessages = async (chatId) => {
    try {
      const res = await getMessages(chatId)
      setMessages(res.data)
    } catch (e) {
      console.error('Failed to load messages', e)
    }
  }

  const handleSend = async () => {
    if (!input.trim() || loading) return

    const userText    = input.trim()
    const assistantId = Date.now() + 1
    setInput('')

    // Optimistically add user message + empty assistant placeholder
    setMessages(prev => [
      ...prev,
      { id: Date.now(), role: 'user',      content: userText, sources: [] },
      { id: assistantId, role: 'assistant', content: '',       sources: [] },
    ])
    setLoading(true)

    try {
      const response = await streamMessage({
        message:    userText,
        chat_id:    chat?.id || null,
        project_id: project?.id || null,
      })

      if (!response.ok) throw new Error(`HTTP ${response.status}`)

      // Connection established — hide the loading dots and start streaming
      setLoading(false)

      const reader  = response.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''
      let   chatNotified = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()   // keep any partial line for the next chunk

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          try {
            const event = JSON.parse(raw)

            if (event.type === 'start') {
              // notify parent about newly created chat (only once)
              if (!chat && !chatNotified) {
                chatNotified = true
                onChatCreated?.({ id: event.chat_id, title: userText.slice(0, 50) })
              }
              // attach source badges as soon as we know them
              setMessages(prev => prev.map(m =>
                m.id === assistantId ? { ...m, sources: event.sources || [] } : m
              ))
            } else if (event.type === 'token') {
              setMessages(prev => prev.map(m =>
                m.id === assistantId ? { ...m, content: m.content + event.content } : m
              ))
            }
          } catch { /* ignore malformed SSE lines */ }
        }
      }
    } catch (e) {
      setLoading(false)
      setMessages(prev => prev.map(m =>
        m.id === assistantId
          ? { ...m, content: 'Sorry, something went wrong. Make sure Ollama is running (`ollama serve`).' }
          : m
      ))
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Top bar */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <span className="text-sm font-medium text-gray-800 truncate">
          {chat?.title || 'New chat'}
        </span>
        {project && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-medium">
            {project.name}
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4">
        {messages.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center text-center py-16">
            <Bot size={32} className="text-gray-300 mb-3" />
            <p className="text-sm text-gray-500 font-medium">Your vault docs are ready</p>
            <p className="text-xs text-gray-400 mt-1">Ask anything — relevant documents are retrieved automatically</p>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${
              msg.role === 'user' ? 'bg-blue-100' : 'bg-gray-100 border border-gray-200'
            }`}>
              {msg.role === 'user'
                ? <User size={13} className="text-blue-700" />
                : <Bot size={13} className="text-gray-600" />
              }
            </div>
            <div className={`max-w-[75%] ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
              <div className={`px-3 py-2 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-blue-50 text-blue-900 rounded-tr-sm'
                  : 'bg-gray-50 text-gray-800 rounded-tl-sm border border-gray-100'
              }`}>
                {msg.content}
              </div>
              {msg.sources?.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                  <Database size={10} className="text-gray-400" />
                  {msg.sources.map((s, i) => (
                    <span key={i} className="text-xs px-2 py-0.5 rounded-full border border-gray-200 text-gray-500 bg-white">
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center flex-shrink-0">
              <Bot size={13} className="text-gray-600" />
            </div>
            <div className="bg-gray-50 border border-gray-100 rounded-2xl rounded-tl-sm px-3 py-2">
              <div className="flex gap-1">
                <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-100">
        <div className="flex items-end gap-2 border border-gray-200 rounded-xl px-3 py-2 focus-within:border-gray-300">
          <textarea
            className="flex-1 resize-none outline-none text-sm text-gray-800 bg-transparent placeholder-gray-400 max-h-24"
            placeholder="Ask anything — vault docs retrieved automatically…"
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="w-7 h-7 rounded-lg bg-gray-900 flex items-center justify-center disabled:opacity-40 hover:bg-gray-700 transition-colors flex-shrink-0"
          >
            <Send size={13} className="text-white" />
          </button>
        </div>
        <p className="text-xs text-gray-400 text-center mt-1.5">
          <Database size={10} className="inline mr-1" />
          Vault docs auto-retrieved · Powered by Ollama (local, free)
        </p>
      </div>
    </div>
  )
}
