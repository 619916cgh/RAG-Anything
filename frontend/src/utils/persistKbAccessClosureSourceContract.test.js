import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const source = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('administrator editing stays users:write-gated and does not revive retired grants', () => {
  const users = source('../pages/AdminUsersPage.jsx')
  const editor = source('../components/EditUserModal.jsx')

  assert.match(users, /const canManageUsers = hasPermission\('users:write'\)/)
  assert.match(users, /canManageUsers && \(/)
  assert.doesNotMatch(users, /allowed_kbs/)
  assert.doesNotMatch(editor, /allowed_kbs/)
  assert.doesNotMatch(editor, /成员与权限|grant|granting/i)
})

test('KB pages use server capabilities and confirmed list membership for mutations', () => {
  const page = source('../pages/KnowledgePage.jsx')
  const detail = source('../pages/KnowledgeDetailPage.jsx')
  const chunks = source('../pages/DocumentChunksPage.jsx')

  assert.match(page, /knowledgeBase\?\.capabilities\?\.delete !== true/)
  assert.match(detail, /hasPermission\('kb:write'\) && canOperateKB/)
  assert.match(chunks, /kbAccess\.capabilities\?\.operate === true/)
  assert.match(detail, /useConfirmedKnowledgeBase\(kbName\)/)
})

test('capability projection keeps role-derived readable KBs read-only where applicable', () => {
  const editor = source('../utils/knowledgeBaseEditor.js')
  const detail = source('../pages/KnowledgeDetailPage.jsx')
  assert.match(editor, /capabilities\.rename === true/)
  assert.match(detail, /kbAccess\.capabilities\?\.operate === true/)
})
