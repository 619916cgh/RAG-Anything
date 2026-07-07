import { useState, useEffect, useRef, useCallback } from 'react'
import { Plus, Layers, Trash2, Clock, Database, FileText, Hash, X, Search } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { api, setCurrentKB, getCurrentKB } from '../utils/api'
import Pagination from '../components/Pagination'

const PAGE_SIZE = 8

// ====================== 知识库选择器（卡片网格） ======================
function KBSelector({ kbs, activeKB, kbStats, onSwitch, onDelete, deletingKB }) {
  const [showDelete, setShowDelete] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const handleDeleteClick = (e, kb) => {
    e.stopPropagation()
    setDeleteTarget(kb)
    setShowDelete(true)
  }

  const formatDate = (iso) => {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
    } catch {
      return iso.slice(0, 10)
    }
  }

  return (
    <div className="resource-grid resource-grid-kbs">
      {kbs.map(kb => {
        const isActive = kb.name === activeKB
        const stats = kbStats[kb.name]

        return (
          <motion.button
            key={kb.name}
            layout
            onClick={() => onSwitch(kb.name)}
            className={`directory-card resource-card group cursor-pointer ${isActive ? 'directory-card-active' : ''}`}
          >
            {isActive && (
              <span className="od-pill absolute top-3 right-3">当前启用</span>
            )}

            <div className="directory-icon">
              <Database size={20} />
            </div>

            <h3 className="text-base font-semibold mb-1 truncate pr-16 text-ink-primary">
              {kb.label || kb.name}
            </h3>
            <p className="text-2xs text-ink-muted mb-3 truncate font-mono">/{kb.name}</p>

            <div className="flex items-center gap-4 text-2xs text-ink-muted mb-2 rounded-lg border border-cloud-300 bg-cloud-50 px-3 py-2">
              {stats !== undefined ? (
                <>
                  <span className="flex items-center gap-1" title="文档数"><FileText size={10} />{stats.documents || 0}</span>
                  <span className="flex items-center gap-1" title="实体数"><Hash size={10} />{stats.entities || 0}</span>
                </>
              ) : (
                <span className="text-ink-muted/60">加载中…</span>
              )}
            </div>

            <div className="directory-footer text-2xs text-ink-muted">
              <span className="flex items-center gap-1"><Clock size={10} />{kb.created ? formatDate(kb.created) : '暂无日期'}</span>
              {kb.owner_username && <span className="od-pill truncate">@{kb.owner_username}</span>}
            </div>

            {kb.name !== 'default' && (
              <button
                onClick={(e) => handleDeleteClick(e, kb)}
                className="absolute bottom-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg text-ink-muted hover:text-rose-500 hover:bg-rose-50"
                title="删除知识库"
              >
                <Trash2 size={13} />
              </button>
            )}
          </motion.button>
        )
      })}

      {/* 删除确认 */}
      <AnimatePresence>
        {showDelete && deleteTarget && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-sky-900/20"
            onClick={() => { setShowDelete(false); setDeleteTarget(null) }}
            role="dialog"
            aria-modal="true"
            aria-label="确认删除知识库"
          >
            <div className="card p-6 max-w-sm w-full m-4" onClick={e => e.stopPropagation()}>
              <Trash2 size={32} className="mx-auto mb-3 text-rose-500" />
              <p className="text-ink-primary font-medium text-center mb-1">确认删除知识库</p>
              <p className="text-sm text-ink-muted text-center mb-2">
                「{deleteTarget.label || deleteTarget.name}」
              </p>
              <p className="text-xs text-rose-500 text-center mb-4">将清除所有文档、实体和向量数据，不可恢复</p>
              <div className="flex gap-3 justify-center">
                <button className="btn-secondary text-sm" onClick={() => { setShowDelete(false); setDeleteTarget(null) }}>取消</button>
                <button
                  className="btn-danger text-sm"
                  disabled={deletingKB}
                  onClick={() => onDelete(deleteTarget.name, () => { setShowDelete(false); setDeleteTarget(null) })}
                >
                  {deletingKB ? '删除中…' : '确认删除'}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ====================== 主页面 ======================
export default function KnowledgePage() {
  const navigate = useNavigate()
  const [kbs, setKBs] = useState([])
  const [activeKB, setActiveKB] = useState(null)
  const [kbsLoaded, setKbsLoaded] = useState(false)
  const [deletingKB, setDeletingKB] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newKBName, setNewKBName] = useState('')
  const [toast, setToast] = useState(null)
  const [kbStats, setKbStats] = useState({})
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const genRef = useRef(0)
  const createInputRef = useRef()

  useEffect(() => { if (showCreate && createInputRef.current) createInputRef.current.focus() }, [showCreate])
  useEffect(() => { setPage(1) }, [search])

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  // 加载知识库列表
  const loadKBs = useCallback(async () => {
    const r = await api.listKBs().catch(() => null)
    if (r) {
      const kbList = r.knowledge_bases || []
      setKBs(kbList)
      const current = getCurrentKB()

      if (current && kbList.some(kb => kb.name === current)) {
        setActiveKB(current)
      } else if (r.active && kbList.some(kb => kb.name === r.active)) {
        setActiveKB(r.active)
        setCurrentKB(r.active)
      } else if (kbList.length > 0) {
        setActiveKB(kbList[0].name)
        setCurrentKB(kbList[0].name)
      }

      // 顺序获取所有知识库统计，避免模块级 currentKB 产生竞争
      const gen = ++genRef.current
      const statsMap = {}
      const prevKB = getCurrentKB()

      for (const kb of kbList) {
        try {
          setCurrentKB(kb.name)
          const s = await api.getStats()
          if (gen === genRef.current) statsMap[kb.name] = s
        } catch {
          // 跳过统计失败的知识库
        }
      }

      setCurrentKB(prevKB)
      if (gen === genRef.current) setKbStats(statsMap)
    }

    setKbsLoaded(true)
  }, [])

  useEffect(() => { loadKBs() }, [loadKBs])

  // 跳转到知识库详情页
  const switchKB = useCallback((name) => {
    setActiveKB(name)
    setCurrentKB(name)
    navigate(`/knowledge/${name}`)
  }, [navigate])

  // 创建知识库
  const createKB = useCallback(async (name) => {
    try {
      await api.createKB(name, name)
      showToast(`知识库 "${name}" 创建成功`, 'success')
      setNewKBName('')
      setShowCreate(false)
      loadKBs()
    } catch (e) {
      showToast('创建失败: ' + e.message, 'error')
    }
  }, [loadKBs])

  const openCreateModal = useCallback(() => {
    setShowCreate(true)
  }, [])

  const closeCreateModal = useCallback(() => {
    setShowCreate(false)
    setNewKBName('')
  }, [])

  const handleCreateKB = useCallback(() => {
    const name = newKBName.trim()
    if (!name) return
    createKB(name)
  }, [createKB, newKBName])

  // 删除知识库
  const deleteKB = useCallback(async (name, onDone) => {
    setDeletingKB(true)
    try {
      await api.deleteKB(name)
      showToast(`知识库 "${name}" 已删除`, 'success')
      onDone?.()
      loadKBs()
    } catch (e) {
      showToast('删除失败: ' + e.message, 'error')
    }
    setDeletingKB(false)
  }, [loadKBs])

  const normalizedSearch = search.trim().toLowerCase()
  const filteredKBs = kbs.filter(kb => {
    if (!normalizedSearch) return true
    const stats = kbStats[kb.name]
    return [
      kb.name,
      kb.label,
      kb.owner_username,
      stats?.documents,
      stats?.entities,
    ].some(value => String(value || '').toLowerCase().includes(normalizedSearch))
  })

  const totalPages = Math.max(1, Math.ceil(filteredKBs.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const paginatedKBs = filteredKBs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  return (
    <div className="resource-page resource-page-kbs">
      {/* 页面头部 */}
      <div className="page-header page-header-divider resource-page-header">
        <div>
          <h2 className="page-title">知识库</h2>
          <p className="page-subtitle">选择一个知识库查看文档、图谱和实体</p>
        </div>
        <button onClick={openCreateModal} className="btn-primary">
          <Plus size={16} /> 新建知识库
        </button>
      </div>

      <section className="resource-panel">
        <div className="resource-toolbar">
          <div className="relative w-full lg:max-w-md">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none" />
            <input
              className="input-field w-full pl-10 pr-4 text-sm"
              placeholder="搜索知识库名称、拥有者或统计信息"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="resource-count">
            共 {kbs.length} 个知识库
            {normalizedSearch ? `，匹配到 ${filteredKBs.length} 个结果` : ''}
          </div>
        </div>

        <KBSelector
          kbs={paginatedKBs}
          activeKB={activeKB}
          kbStats={kbStats}
          onSwitch={switchKB}
          onDelete={deleteKB}
          deletingKB={deletingKB}
        />

        {filteredKBs.length > 0 && (
          <Pagination page={currentPage} totalPages={totalPages} onPageChange={setPage} className="resource-pagination" />
        )}

        {/* 尚未加载知识库时的空状态 */}
        {kbsLoaded && kbs.length === 0 && (
          <div className="empty-state resource-empty-state">
            <Layers size={48} className="mx-auto mb-4 text-cloud-400" />
            <p className="text-ink-muted text-sm mb-2">还没有知识库</p>
            <button onClick={openCreateModal} className="btn-primary text-sm">
              <Plus size={16} /> 新建知识库
            </button>
          </div>
        )}

        {kbs.length > 0 && filteredKBs.length === 0 && (
          <div className="empty-state resource-empty-state">
            <Search size={40} className="mx-auto mb-4 text-cloud-400" />
            <p className="text-ink-primary text-sm font-medium mb-2">没有找到匹配的知识库</p>
            <p className="text-ink-muted text-sm">试试搜索名称、拥有者，或者文档与实体数量</p>
          </div>
        )}
      </section>

      {/* 创建知识库弹窗 */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-sky-900/20"
            onClick={closeCreateModal}
            role="dialog"
            aria-modal="true"
            aria-label="新建知识库"
          >
            <motion.div
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 16, scale: 0.96 }}
              transition={{ duration: 0.18 }}
              className="card p-6 max-w-sm w-full m-4"
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-4 mb-5">
                <div>
                  <p className="text-base font-semibold text-ink-primary">新建知识库</p>
                  <p className="text-xs text-ink-muted mt-1">创建新的文档、实体与图谱空间</p>
                </div>
                <button
                  className="p-1.5 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-cloud-200 transition-colors"
                  onClick={closeCreateModal}
                  aria-label="关闭"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="text-xs text-ink-muted mb-1.5 block">知识库名称</label>
                  <input
                    ref={createInputRef}
                    className="input-field text-sm w-full"
                    placeholder="输入知识库名称…"
                    value={newKBName}
                    maxLength={64}
                    onChange={e => setNewKBName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') handleCreateKB()
                      if (e.key === 'Escape') closeCreateModal()
                    }}
                  />
                </div>
                <div className="flex gap-2 justify-end">
                  <button className="btn-secondary text-sm" onClick={closeCreateModal}>取消</button>
                  <button className="btn-primary text-sm" onClick={handleCreateKB} disabled={!newKBName.trim()}>创建</button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 提示消息 */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            role="status"
            aria-live="polite"
            className={`fixed bottom-6 right-6 px-5 py-3 rounded-2xl text-sm font-medium z-50 shadow-cloud-md ${
              toast.type === 'error' ? 'toast-error' : toast.type === 'success' ? 'toast-success' : 'toast-info'
            }`}
          >
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
