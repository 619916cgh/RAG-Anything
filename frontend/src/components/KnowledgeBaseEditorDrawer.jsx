import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, X } from 'lucide-react'
import SideDrawer from './SideDrawer'
import { api } from '../utils/api'
import { getKnowledgeBaseEditCapabilities } from '../utils/knowledgeBaseEditor'

export default function KnowledgeBaseEditorDrawer({ kb, isOpen, onRequestClose, onSaved }) {
  const labelInputRef = useRef(null)
  const [label, setLabel] = useState('')
  const [metadataRevision, setMetadataRevision] = useState(null)
  const [savingLabel, setSavingLabel] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const canRename = getKnowledgeBaseEditCapabilities(kb).rename

  useEffect(() => {
    if (!isOpen || !kb) return
    setLabel(kb.label || kb.name || '')
    setMetadataRevision(kb.updated_at || kb.last_updated_at || null)
    setError('')
    setNotice('')
  }, [isOpen, kb])

  const saveLabel = async () => {
    const displayName = label.trim()
    if (!kb || !canRename || !displayName || savingLabel) return
    setSavingLabel(true)
    setError('')
    setNotice('')
    try {
      const result = await api.updateKBMetadata(kb.name, {
        display_name: displayName,
        expected_updated_at: metadataRevision,
      })
      const updated = result?.knowledge_base || result?.kb || result
      setMetadataRevision(updated?.updated_at || metadataRevision)
      setNotice('显示名称已保存')
      onSaved?.(updated)
    } catch (requestError) {
      setError(requestError.message || '显示名称保存失败')
    } finally {
      setSavingLabel(false)
    }
  }

  if (!kb || !canRename) return null

  return (
    <SideDrawer isOpen={isOpen} onRequestClose={onRequestClose} ariaLabel={`编辑知识库 ${kb.label || kb.name}`} initialFocusRef={labelInputRef} size="lg">
      <div className="flex h-full min-h-0 flex-col bg-white dark:bg-[#0f1d2e]">
        <header className="flex min-h-16 shrink-0 items-center justify-between gap-3 border-b border-cloud-200 px-4 sm:px-5">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink-primary">编辑知识库</h2>
            <p className="truncate text-xs text-ink-muted">{kb.label || kb.name}</p>
          </div>
          <button type="button" onClick={onRequestClose} className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-cloud-100 hover:text-ink-primary" aria-label="关闭知识库编辑">
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {error && <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">{error}</p>}
          {notice && <p className="mb-4 flex items-center gap-2 rounded-lg border border-sage-200 bg-sage-50 px-3 py-2 text-sm text-sage-700" role="status"><Check size={16} aria-hidden="true" />{notice}</p>}
          <section aria-label="基本信息" className="space-y-5">
            <div>
              <label htmlFor="kb-display-name" className="mb-1.5 block text-sm font-medium text-ink-body">显示名称</label>
              <input ref={labelInputRef} id="kb-display-name" className="input-field w-full text-sm" value={label} maxLength={128} onChange={(event) => setLabel(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void saveLabel() }} />
              <p className="mt-2 text-xs leading-5 text-ink-muted">仅修改列表和页面中的显示名称，不会修改知识库标识、文档或索引。</p>
            </div>
            <div>
              <span className="mb-1.5 block text-sm font-medium text-ink-body">知识库标识</span>
              <output className="block break-all rounded-lg border border-cloud-200 bg-cloud-50 px-3 py-2 font-mono text-xs text-ink-muted">{kb.name}</output>
            </div>
            <button type="button" onClick={() => void saveLabel()} disabled={savingLabel || !label.trim()} className="btn-primary min-h-11 text-sm disabled:opacity-50">
              {savingLabel && <Loader2 size={15} className="animate-spin" aria-hidden="true" />}
              {savingLabel ? '保存中...' : '保存显示名称'}
            </button>
          </section>
        </div>
      </div>
    </SideDrawer>
  )
}
