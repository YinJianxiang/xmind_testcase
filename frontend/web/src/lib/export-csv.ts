import type { MindMapNode, TestCaseItem } from '@/types/agent'
import { cleanPreconditionPrefix, cleanPriorityPrefix } from '@/lib/mindmap-client'

export type CsvCaseRow = {
  testName: string
  priority: string
  precondition: string
  steps: string
  expected: string
}

function extractPriority(text: string) {
  const match = text.match(/^\s*\[?\s*(P[0-3])\s*\]?\s*[-:：]?/i)
  return match ? match[1].toUpperCase() : ''
}

function cleanName(text: string) {
  return cleanPriorityPrefix(text)
}

function extractLabeledContent(text: string, label: '测试步骤' | '期望结果') {
  const normalized = (text || '').replace(/\r/g, '')
  const lines = normalized.split('\n')
  if (lines.length === 0) return ''

  const firstLine = lines[0].trim()
  const regex = new RegExp(`^${label}(\\s*\\d+)?\\s*[:：-]?\\s*(.*)$`)
  const match = firstLine.match(regex)
  if (!match) return normalized.trim()

  const inline = (match[2] || '').trim()
  const rest = lines.slice(1).join('\n').trim()
  if (inline && rest) return `${inline}\n${rest}`
  return inline || rest
}

export function parseStepAndExpected(testNode: MindMapNode) {
  const stepsList: string[] = []
  const expectedList: string[] = []

  for (const child of testNode.children) {
    const childText = child.data.text || ''

    if (childText.includes('测试步骤')) {
      stepsList.push(extractLabeledContent(childText, '测试步骤'))
      const nestedExpected = child.children.find((c) => c.data.text.includes('期望结果'))
      if (nestedExpected) {
        expectedList.push(extractLabeledContent(nestedExpected.data.text, '期望结果'))
      }
    }

    if (childText.includes('期望结果') && expectedList.length === 0) {
      expectedList.push(extractLabeledContent(childText, '期望结果'))
    }
  }

  return {
    steps: stepsList.join('\n'),
    expected: expectedList.join('\n'),
  }
}

export function extractCasesFromMindMap(root: MindMapNode): CsvCaseRow[] {
  const rows: CsvCaseRow[] = []
  const level1 = root.data.text.startsWith('@') ? root.children : [root]

  for (const categoryNode of level1) {
    const category = categoryNode.data.text.replace(/^@/, '').trim() || '未分类'
    for (const preconditionNode of categoryNode.children) {
      const precondition = cleanPreconditionPrefix(preconditionNode.data.text) || '无'
      for (const testNode of preconditionNode.children) {
        const detail = parseStepAndExpected(testNode)
        rows.push({
          testName: `${category}-${cleanName(testNode.data.text)}`,
          priority: testNode.data.priority || extractPriority(testNode.data.text),
          precondition,
          steps: detail.steps,
          expected: detail.expected,
        })
      }
    }
  }

  return rows
}

function exportCaseId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '').slice(0, 16)
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

function normalizePriority(raw: string | undefined): TestCaseItem['priority'] {
  const p = (raw || '').toUpperCase()
  if (p === 'P0' || p === 'P1' || p === 'P2' || p === 'P3') return p
  return 'P2'
}

/** 与 CSV 导出同一遍历逻辑，供 XMind 等在 testCases 已被清空时从脑图还原结构化用例。 */
export function extractTestCaseItemsFromMindMap(root: MindMapNode): TestCaseItem[] {
  const items: TestCaseItem[] = []
  const level1 = root.data.text.startsWith('@') ? root.children : [root]

  for (const categoryNode of level1) {
    const category = categoryNode.data.text.replace(/^@/, '').trim() || '未分类'
    for (const preconditionNode of categoryNode.children) {
      const precondition = cleanPreconditionPrefix(preconditionNode.data.text) || '无'
      for (const testNode of preconditionNode.children) {
        const detail = parseStepAndExpected(testNode)
        const pr = normalizePriority(testNode.data.priority || extractPriority(testNode.data.text))
        const id =
          typeof testNode.data.id === 'string' && testNode.data.id.trim()
            ? testNode.data.id.trim()
            : typeof testNode.data.uid === 'string' && testNode.data.uid.trim()
              ? testNode.data.uid.trim()
              : exportCaseId()
        items.push({
          id,
          category,
          topic: cleanName(testNode.data.text),
          precondition,
          steps: detail.steps,
          expected: detail.expected,
          priority: pr,
        })
      }
    }
  }

  return items
}

function escapeCell(value: string) {
  return `"${value.replace(/"/g, '""')}"`
}

export function buildCsvFromMindMap(root: MindMapNode): string | null {
  const header = ['测试名称', '优先级', '前置条件', '测试步骤', '期望结果']
  const rows = extractCasesFromMindMap(root)

  if (rows.length === 0) return null

  const body = rows.map((r) =>
    [r.testName, r.priority, r.precondition, r.steps, r.expected].map((v) => escapeCell(v || '')).join(','),
  )

  return [header.join(','), ...body].join('\n')
}

/** @returns 是否已触发下载（有至少一行用例） */
export function downloadTestCasesCsv(root: MindMapNode, filename = `test-cases-${Date.now()}.csv`): boolean {
  const csv = buildCsvFromMindMap(root)
  if (!csv) return false

  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  return true
}
