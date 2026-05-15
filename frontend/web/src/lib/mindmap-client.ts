import type { MindMapNode } from '@/types/agent'

export const PRECONDITION_TAG = '前置' as const

export const EMPTY_MAP: MindMapNode = {
  data: { text: '@测试用例', uid: 'root', id: 'root' },
  children: [],
}

export function normalizeMindMap(input: unknown): MindMapNode {
  const node = input as {
    data?: { text?: unknown; uid?: unknown; id?: unknown; tag?: unknown; priority?: unknown }
    children?: unknown
  }
  const text = typeof node?.data?.text === 'string' && node.data.text.trim() ? node.data.text : '未命名节点'
  const childrenRaw = Array.isArray(node?.children) ? node.children : []
  const rawTags = Array.isArray(node?.data?.tag) ? node.data.tag.map(String).filter(Boolean) : []
  const priority =
    typeof node?.data?.priority === 'string' && /^P[0-3]$/i.test(node.data.priority)
      ? (node.data.priority.toUpperCase() as 'P0' | 'P1' | 'P2' | 'P3')
      : ((rawTags.find((tag) => /^P[0-3]$/i.test(tag))?.toUpperCase() as
          | 'P0'
          | 'P1'
          | 'P2'
          | 'P3'
          | undefined) || extractPriorityFromText(text))
  const hasPreconditionTag = rawTags.includes(PRECONDITION_TAG) || text.trim().startsWith('!')
  const businessTags = rawTags.filter((tag) => !/^P[0-3]$/i.test(tag) && tag !== PRECONDITION_TAG)
  const tag = [
    ...(priority ? [priority] : []),
    ...(hasPreconditionTag ? [PRECONDITION_TAG] : []),
    ...businessTags,
  ]

  return {
    data: {
      text: cleanPreconditionPrefix(priority ? cleanPriorityPrefix(text) || text : text) || text,
      ...(typeof node?.data?.uid === 'string' ? { uid: node.data.uid } : {}),
      ...(typeof node?.data?.id === 'string' ? { id: node.data.id } : {}),
      ...(priority ? { priority } : {}),
      ...(tag.length > 0 ? { tag } : {}),
    },
    children: childrenRaw.map((child) => normalizeMindMap(child)),
  }
}

export function countMindMap(root: MindMapNode) {
  const stats = {
    categories: 0,
    preconditions: 0,
    caseCount: 0,
    priorities: { P0: 0, P1: 0, P2: 0, P3: 0 } as Record<'P0' | 'P1' | 'P2' | 'P3', number>,
  }

  const categoryNodes = root.data.text.startsWith('@') ? root.children : [root]
  stats.categories = categoryNodes.length

  for (const categoryNode of categoryNodes) {
    for (const preconditionNode of categoryNode.children) {
      stats.preconditions += 1
      for (const testNode of preconditionNode.children) {
        stats.caseCount += 1
        const priority = testNode.data.priority || extractPriorityFromText(testNode.data.text)
        if (priority) {
          stats.priorities[priority] += 1
        }
      }
    }
  }

  return stats
}

function extractPriorityFromText(text: string) {
  const match = text.match(/^\s*\[?\s*(P[0-3])\s*\]?\s*[-:：]?/i)
  return match ? (match[1].toUpperCase() as 'P0' | 'P1' | 'P2' | 'P3') : null
}

export function cleanPriorityPrefix(text: string) {
  return text.replace(/^\s*\[?\s*P[0-3]\s*\]?\s*[-:：]?\s*/i, '').trim()
}

export function cleanPreconditionPrefix(text: string) {
  return text.replace(/^\s*!\s*/, '').trim()
}

function normalizeModuleTitle(text: string) {
  return (text || '').replace(/^@/, '').trim().toLowerCase()
}

export function sameModuleNode(left: MindMapNode, right: MindMapNode) {
  const leftId = left.data.uid || left.data.id
  const rightId = right.data.uid || right.data.id
  if (leftId && rightId && leftId === rightId) return true
  return normalizeModuleTitle(left.data.text) === normalizeModuleTitle(right.data.text)
}

export function mergeModuleMindMap(root: MindMapNode, moduleMindMap: MindMapNode): MindMapNode {
  const normalizedRoot = normalizeMindMap(root)
  const normalizedModule = normalizeMindMap(moduleMindMap)
  let replaced = false

  const children = normalizedRoot.children.map((child) => {
    if (sameModuleNode(child, normalizedModule)) {
      replaced = true
      return normalizedModule
    }
    return child
  })

  return {
    ...normalizedRoot,
    children: replaced ? children : [...children, normalizedModule],
  }
}
