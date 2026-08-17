import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = relativePath => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('knowledge-base editing is capability-gated and no longer uses user-admin grants', () => {
  const page = source('../pages/KnowledgePage.jsx')
  const drawer = source('../components/KnowledgeBaseEditorDrawer.jsx')
  const userEditor = source('../components/EditUserModal.jsx')

  assert.match(page, /canEditKnowledgeBase\(kb\)/)
  assert.match(drawer, /getKnowledgeBaseEditCapabilities\(kb\)/)
  assert.doesNotMatch(drawer, /member\.is_owner/)
  assert.doesNotMatch(drawer, /成员与权限/)
  assert.doesNotMatch(drawer, /getKBMembers/)
  assert.match(drawer, /min-h-11 min-w-11/)
  assert.doesNotMatch(userEditor, /allowed_kbs/)
})
