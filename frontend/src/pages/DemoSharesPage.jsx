import { useEffect, useMemo, useState } from 'react'
import { Copy, Link2, Loader2, Plus, ShieldAlert, Trash2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { api } from '../utils/api'
import { getKnowledgeBaseDisplayName } from '../utils/kbDisplayName'

export default function DemoSharesPage({ onToast }) {
  const { isAdmin } = useAuth()
  const [agents, setAgents] = useState([])
  const [shares, setShares] = useState([])
  const [agentId, setAgentId] = useState('')
  const [busy, setBusy] = useState(false)
  const [createdUrl, setCreatedUrl] = useState('')
  const [error, setError] = useState('')

  const shareableAgents = useMemo(() => agents.filter(agent => agent.kb_name), [agents])
  const refresh = async () => {
    setError('')
    const [agentResult, shareResult] = await Promise.all([api.listAgents(), api.listDemoShares()])
    setAgents(agentResult.agents || [])
    setShares(shareResult.shares || [])
  }
  useEffect(() => { if (isAdmin) refresh().catch(err => setError(err.message || '加载失败')) }, [isAdmin])

  const create = async () => {
    if (!agentId) return
    setBusy(true); setError(''); setCreatedUrl('')
    try {
      const result = await api.createDemoShare(agentId)
      const url = `${window.location.origin}/demo/${result.share.share_id}#${result.token}`
      setCreatedUrl(url)
      setShares(previous => [result.share, ...previous])
      onToast?.('已创建演示链接，请立即复制并妥善保存', 'success')
    } catch (err) { setError(err.message || '创建失败') } finally { setBusy(false) }
  }
  const revoke = async shareId => {
    setBusy(true); setError('')
    try {
      await api.revokeDemoShare(shareId)
      setShares(previous => previous.map(share => share.share_id === shareId ? { ...share, revoked_at: new Date().toISOString() } : share))
      onToast?.('演示链接已撤销', 'success')
    } catch (err) { setError(err.message || '撤销失败') } finally { setBusy(false) }
  }
  const copy = async value => {
    try { await navigator.clipboard.writeText(value); onToast?.('链接已复制', 'success') } catch { setError('浏览器未允许复制，请手动复制链接') }
  }

  if (!isAdmin) return <div className="preferences-alert preferences-alert-error"><ShieldAlert size={18} />此页面仅限超级管理员使用。</div>
  return <div className="resource-page demo-shares-page">
    <header className="resource-page-header"><div><p className="resource-page-kicker">公开演示</p><h2>云端问答链接</h2><p>每条链接固定到一个智能体与其云端知识库，可随时撤销。</p></div></header>
    <section className="demo-shares-create">
      <label htmlFor="demo-agent">演示智能体</label>
      <select id="demo-agent" className="input-field" value={agentId} onChange={event => setAgentId(event.target.value)} disabled={busy}>
        <option value="">选择已绑定知识库的智能体</option>
        {shareableAgents.map(agent => <option value={agent.id} key={agent.id}>{agent.name} - {getKnowledgeBaseDisplayName(agent)}</option>)}
      </select>
      <button className="btn-primary" onClick={create} disabled={!agentId || busy}>{busy ? <Loader2 className="animate-spin" size={16} /> : <Plus size={16} />}创建链接</button>
    </section>
    {createdUrl && <section className="demo-shares-created"><div><strong>新链接仅显示这一次</strong><code>{createdUrl}</code></div><button className="btn-secondary" onClick={() => copy(createdUrl)}><Copy size={16} />复制</button></section>}
    {error && <p className="preferences-alert preferences-alert-error">{error}</p>}
    <section className="demo-shares-list" aria-label="现有演示链接">
      {shares.map(share => <article key={share.share_id} className="demo-share-row">
        <div><strong>{share.agent_name || '智能体'}</strong><span>{getKnowledgeBaseDisplayName(share)}</span><small>{share.revoked_at ? '已撤销' : '有效'} · {share.max_requests_per_minute}/分钟 · 最多 {share.max_concurrent_queries} 并发</small></div>
        {!share.revoked_at && <button className="btn-danger" disabled={busy} onClick={() => revoke(share.share_id)} aria-label="撤销演示链接" title="撤销演示链接"><Trash2 size={16} /></button>}
      </article>)}
      {!shares.length && <p className="public-demo-status">尚未创建演示链接。</p>}
    </section>
  </div>
}
