import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ArrowDown, Bot, Database, Expand, RotateCcw, Send, Sparkles, Square } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { controlledDemoMediaUrl, loadPublicDemo, readDemoToken, streamPublicDemo } from '../utils/publicDemoClient'
import { formatPublicDemoMarkdown, isCompactEntity, parseDemoDisplayMarker } from '../utils/publicDemoMarkdown'

const EMPTY_MESSAGE = { role: 'assistant', content: '' }

const demoMarkdown = {
  h1: ({ children }) => <h2>{children}</h2>,
  h2: ({ children }) => <h2>{children}</h2>,
  h3: ({ children }) => <h3>{children}</h3>,
  p: ({ children }) => {
    const value = Array.isArray(children) ? children.join('') : children
    const marker = parseDemoDisplayMarker(value)
    if (marker?.type === 'entity') return <span className="public-demo-entity">{marker.value}</span>
    if (marker?.type === 'relation') return <div className="public-demo-relation"><span>{marker.source}</span><i>{marker.relation}</i><b>→</b><span>{marker.target}</span></div>
    return <p>{children}</p>
  },
  ul: ({ children }) => <ul>{children}</ul>,
  ol: ({ children }) => <ol>{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong>{children}</strong>,
  code: ({ inline, children }) => {
    const value = String(children || '').replace(/\n$/, '').trim()
    if (!inline && isCompactEntity(value)) return <span className="public-demo-entity">{value}</span>
    return inline ? <code>{children}</code> : <pre><code>{children}</code></pre>
  },
  table: ({ children }) => <div className="public-demo-table-wrap"><table>{children}</table></div>,
  blockquote: ({ children }) => <blockquote>{children}</blockquote>,
  hr: () => <hr />,
  a: ({ children }) => <span>{children}</span>,
}

const getDemoEvidence = message => {
  const sources = Array.isArray(message.sources)
    ? message.sources.filter(source => typeof source?.name === 'string' && source.name.trim())
    : []
  const citations = !sources.length && Array.isArray(message.citations)
    ? message.citations.filter(citation => citation?.document_name || citation?.caption)
    : []
  const media = Array.isArray(message.images)
    ? message.images.filter(item => item?.media_id && typeof item?.url === 'string')
    : []
  return { sources, citations, media, count: sources.length || citations.length || 0, hasEvidence: sources.length > 0 || citations.length > 0 || media.length > 0 }
}

export default function PublicDemoPage() {
  const { shareId = '' } = useParams()
  const tokenRef = useRef(readDemoToken())
  const abortRef = useRef(null)
  const feedRef = useRef(null)
  const followOutputRef = useRef(true)
  const [demo, setDemo] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [streamStatus, setStreamStatus] = useState('')
  const [showScrollButton, setShowScrollButton] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    setDemo(null)
    setMessages([])
    setError('')
    setStreamStatus('')
    setLoading(true)
    if (!tokenRef.current) {
      setLoading(false)
      setError('演示链接无效或已失效')
      return () => controller.abort()
    }
    loadPublicDemo(shareId, tokenRef.current, controller.signal)
      .then(setDemo)
      .catch(err => setError(err.message || '演示链接无效或已失效'))
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [shareId])

  const scrollToBottom = useCallback((behavior = 'smooth') => {
    const feed = feedRef.current
    if (!feed) return
    followOutputRef.current = true
    setShowScrollButton(false)
    feed.scrollTo({ top: feed.scrollHeight, behavior })
  }, [])

  const handleFeedScroll = useCallback(() => {
    const feed = feedRef.current
    if (!feed) return
    const distanceFromBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight
    const atBottom = distanceFromBottom <= 72
    followOutputRef.current = atBottom
    setShowScrollButton(!atBottom && feed.scrollHeight > feed.clientHeight)
  }, [])

  useEffect(() => {
    if (followOutputRef.current) scrollToBottom('auto')
  }, [messages, sending, scrollToBottom])

  const stop = useCallback(() => {
    const controller = abortRef.current
    if (!controller) return
    controller.abort()
    setMessages(previous => previous.map((message, index) => index === previous.length - 1 && message.role === 'assistant'
      ? { ...message, cancelled: true }
      : message))
    setStreamStatus('回答已停止')
  }, [])
  const clear = useCallback(() => {
    stop()
    setMessages([])
    setError('')
    setStreamStatus('')
  }, [stop])
  const fullscreen = useCallback(() => document.documentElement.requestFullscreen?.().catch(() => {}), [])

  const send = useCallback(async event => {
    event?.preventDefault()
    const query = input.trim()
    if (!query || sending || !demo) return
    const controller = new AbortController()
    abortRef.current = controller
    setInput('')
    setError('')
    followOutputRef.current = true
    setShowScrollButton(false)
    setSending(true)
    setStreamStatus('正在生成回答')
    setMessages(previous => [...previous, { role: 'user', content: query }, { ...EMPTY_MESSAGE }])
    let receivedTerminalEvent = false
    try {
      await streamPublicDemo(shareId, tokenRef.current, query, {
        signal: controller.signal,
        onEvent: eventData => {
          if (abortRef.current !== controller) return
          if (eventData.type === 'token') {
            setMessages(previous => previous.map((message, index) => index === previous.length - 1
              ? { ...message, content: `${message.content}${eventData.content || ''}` }
              : message))
          }
          if (eventData.type === 'done') {
            receivedTerminalEvent = true
            setMessages(previous => previous.map((message, index) => index === previous.length - 1
              ? { ...message, done: true, images: eventData.images || [], sources: eventData.sources || [], citations: eventData.citations || [] }
              : message))
            setStreamStatus('回答已完成')
          }
          if (eventData.type === 'error') {
            receivedTerminalEvent = true
            setError(eventData.content || '问答暂时不可用')
            setStreamStatus('回答未完成')
          }
        },
      })
      if (!receivedTerminalEvent && !controller.signal.aborted) {
        setError('问答连接意外中断，请重试')
        setStreamStatus('回答未完成')
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        setError(err.message || '问答暂时不可用')
        setStreamStatus('回答未完成')
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setSending(false)
    }
  }, [demo, input, sending, shareId])

  const sendOnEnter = useCallback(event => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return
    event.preventDefault()
    send()
  }, [send])

  const kb = demo?.knowledge_base
  return (
    <main className="public-demo" aria-busy={loading}>
      <header className="public-demo-header">
        <div className="public-demo-header-main">
          <div className="public-demo-brand"><span>知元</span><small>云端知识问答</small></div>
          {kb && <div className="public-demo-kb"><Database size={15} /><strong>{kb.name}</strong></div>}
          <button className="public-demo-icon" type="button" onClick={fullscreen} aria-label="全屏演示" title="全屏演示"><Expand size={18} /></button>
        </div>
        {kb && <div className="public-demo-settings" aria-label="知识库设置">
          <span className="public-demo-settings-label">知识库设置</span>
          <span>新上传默认</span><span>解析：{kb.parser}</span><span>分块：{kb.chunking_strategy}</span>
        </div>}
      </header>
      <section ref={feedRef} onScroll={handleFeedScroll} className="public-demo-feed" aria-busy={sending}>
        <p className="sr-only" role="status" aria-live="polite">{streamStatus}</p>
        {loading && <div className="public-demo-loading"><span /><span /><span /></div>}
        {!loading && error && !demo && <p className="public-demo-error">{error}</p>}
        {demo && messages.length === 0 && <div className="public-demo-welcome"><div className="public-demo-avatar"><Bot size={27} /></div><p className="public-demo-welcome-label">演示助手</p><h1>{demo.agent?.name || '知识问答助手'}</h1><p>{demo.agent?.welcome_message || '请输入问题，系统将基于云端知识库回答。'}</p><div className="public-demo-welcome-hint"><Sparkles size={15} /> 回答仅基于当前知识库内容</div></div>}
        {messages.map((message, index) => {
          const evidence = getDemoEvidence(message)
          return <article className={`public-demo-message ${message.role}`} key={`${message.role}-${index}`}>
          {message.role === 'user' && <div className="public-demo-message-label user-label"><span className="public-demo-message-avatar user-avatar">你</span>你的问题</div>}
          {message.role === 'assistant' && <div className="public-demo-message-label"><span className="public-demo-message-avatar"><Bot size={15} /></span>{demo?.agent?.name || '知识问答助手'}</div>}
          <div className="public-demo-bubble">{message.content
            ? <ReactMarkdown components={demoMarkdown}>{formatPublicDemoMarkdown(message.content)}</ReactMarkdown>
            : (sending && index === messages.length - 1 ? <span className="public-demo-answering"><i /><i /><i /> 正在整理知识库内容</span> : '')}</div>
          {message.cancelled && <p className="public-demo-cancelled">已停止，以上为已生成内容。</p>}
          {message.role === 'assistant' && evidence.hasEvidence && <details className="public-demo-evidence">
            <summary><Database size={14} /> 依据与资料 <span>{evidence.count || evidence.media.length} 项</span></summary>
            {evidence.sources.length > 0 && <section className="public-demo-citations" aria-label="来源引用"><h2>参考来源</h2>{evidence.sources.map((source, sourceIndex) => <p key={`${source.name}-${sourceIndex}`}><span>{sourceIndex + 1}</span>{source.name}</p>)}</section>}
            {evidence.citations.length > 0 && <section className="public-demo-citations" aria-label="来源引用"><h2>参考来源</h2>{evidence.citations.map((citation, citationIndex) => { const name = citation?.document_name || citation?.caption; return <p key={`${name}-${citationIndex}`}><span>{citationIndex + 1}</span>{name}</p> })}</section>}
            {evidence.media.length > 0 && <div className="public-demo-media">{evidence.media.map((media, mediaIndex) => {
              const source = controlledDemoMediaUrl(shareId, media?.url)
              if (!source) return null
              return media.mime?.startsWith('video/')
                ? <video controls key={`${media.media_id}-${mediaIndex}`} src={source} />
                : <img key={`${media.media_id}-${mediaIndex}`} src={source} alt={media.caption || '知识库引用媒体'} loading="lazy" />
            })}</div>}
          </details>}
        </article>
        })}
      </section>
      {showScrollButton && <button className="public-demo-scroll-button" type="button" onClick={() => scrollToBottom()} aria-label="回到底部" title="回到底部"><ArrowDown size={17} /> 新回答</button>}
      {error && demo && <p className="public-demo-error" role="alert">{error}</p>}
      <form className="public-demo-composer" onSubmit={send}>
        <div className="public-demo-composer-inner">
          <textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={sendOnEnter} disabled={!demo || sending} placeholder="向知识库提问..." aria-label="问题" rows="1" />
          {sending ? <button className="public-demo-command" type="button" onClick={stop} aria-label="停止生成" title="停止生成"><Square size={18} /></button> : <button className="public-demo-command primary" disabled={!demo || !input.trim()} aria-label="发送问题" title="发送问题"><Send size={18} /></button>}
          <button className="public-demo-command" type="button" onClick={clear} aria-label="清空本次演示" title="清空本次演示"><RotateCcw size={18} /></button>
        </div>
      </form>
    </main>
  )
}
