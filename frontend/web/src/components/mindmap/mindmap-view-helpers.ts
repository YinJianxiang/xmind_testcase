import type { MindMapNode } from '@/types/agent'
import { EMPTY_MAP, PRECONDITION_TAG } from '@/lib/mindmap-client'
import { cleanPreconditionPrefix, cleanPriorityPrefix } from '@/lib/mindmap-client'

export const TAG_COLORS = {
  P0: '#dc2626',
  P1: '#ea580c',
  P2: '#16a34a',
  P3: '#2563eb',
  前置: '#475569',
} as const

export type Priority = 'P0' | 'P1' | 'P2' | 'P3'

type RawMindMapData = {
  text?: unknown
  topic?: unknown
  uid?: unknown
  id?: unknown
  tag?: unknown
  priority?: unknown
  children?: unknown
}

type RawMindMapNode = {
  data?: RawMindMapData
  children?: unknown
  root?: unknown
}

export type MindMapTagItem = string | { text?: string; value?: string; name?: string }

export type MindMapNodeLike = {
  nodeData?: {
    data?: RawMindMapData
  }
  data?: RawMindMapData
  group?: {
    node?: Element
    el?: Element
  }
}

export type MindMapEventHandlers = {
  handleDataChange: () => void
  handleScale: (scale: number) => void
  handleNodeTreeRenderEnd: () => void
  handleNodeTagClick: (node: MindMapNodeLike, item: MindMapTagItem) => void
}

export type MindMapInstance = {
  view?: {
    scale?: number
    setScale?: (scale: number) => void
    fit?: () => void
    reset?: () => void
  }
  resize?: () => void
  setData?: (data: MindMapNode) => void
  getData?: (withConfig?: boolean) => unknown
  execCommand?: (command: string, ...args: unknown[]) => void
  on?: {
    (eventName: 'scale', handler: (scale: number) => void): void
    (eventName: 'node_tag_click', handler: (node: MindMapNodeLike, item: MindMapTagItem) => void): void
    (eventName: string, handler: (...args: unknown[]) => void): void
  }
  off?: {
    (eventName: 'scale', handler: (scale: number) => void): void
    (eventName: 'node_tag_click', handler: (node: MindMapNodeLike, item: MindMapTagItem) => void): void
    (eventName: string, handler?: (...args: unknown[]) => void): void
  }
  destroy?: () => void
  __handlers?: MindMapEventHandlers
}

export type MindMapConstructor = new (opts: unknown) => MindMapInstance

export type PriorityEditorState = {
  x: number
  y: number
  nodeUid: string
  currentPriority: Priority
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function unescapeHtml(value: string) {
  if (typeof document === 'undefined') return value
  const textarea = document.createElement('textarea')
  textarea.innerHTML = value
  return textarea.value
}

export function normalizePriority(value: unknown): Priority | null {
  if (typeof value !== 'string') return null
  const priority = value.trim().toUpperCase()
  return priority === 'P0' || priority === 'P1' || priority === 'P2' || priority === 'P3' ? priority : null
}

function extractPriority(text: string) {
  const match = text.match(/^\s*\[?\s*(P[0-3])\s*\]?\s*[-:：]?/i)
  return match ? (match[1].toUpperCase() as Priority) : null
}

function normalizeTags(tag: unknown) {
  return Array.isArray(tag) ? tag.map(String).filter(Boolean) : []
}

function firstPriorityFromTags(tags: string[]) {
  return tags.map((tag) => normalizePriority(tag)).find(Boolean) || null
}

export function tagText(item: MindMapTagItem) {
  return typeof item === 'string' ? item : item?.text || item?.value || item?.name || String(item)
}

export function normalizeNodeForMindMap(node: MindMapNode | null | undefined, path: number[] = []): MindMapNode {
  const source = node || EMPTY_MAP
  const rawText = typeof source.data?.text === 'string' && source.data.text.trim() ? source.data.text : '未命名节点'
  const sourceTags = normalizeTags(source.data?.tag)
  const priority = normalizePriority(source.data?.priority) || firstPriorityFromTags(sourceTags) || extractPriority(rawText)
  const uid = source.data?.uid || source.data?.id || (path.length === 0 ? 'root' : `node-${path.join('-')}`)
  const hasPreconditionPrefix = rawText.trim().startsWith('!')
  const hasPreconditionTag = sourceTags.includes(PRECONDITION_TAG) || hasPreconditionPrefix
  const existingTags = sourceTags.filter((tag) => !normalizePriority(tag) && tag !== PRECONDITION_TAG)
  const displayText =
    cleanPreconditionPrefix(priority ? cleanPriorityPrefix(rawText) || rawText : rawText) || rawText
  const nextTags = [
    ...(priority ? [priority] : []),
    ...(hasPreconditionTag ? [PRECONDITION_TAG] : []),
    ...existingTags,
  ]

  return {
    data: {
      ...source.data,
      text: escapeHtml(displayText),
      uid,
      id: source.data?.id || uid,
      ...(priority ? { priority } : {}),
      ...(nextTags.length > 0 ? { tag: nextTags } : {}),
    },
    children: Array.isArray(source.children)
      ? source.children.map((child, index) => normalizeNodeForMindMap(child, [...path, index]))
      : [],
  }
}

function asRawMindMapNode(node: unknown): RawMindMapNode {
  return node && typeof node === 'object' ? (node as RawMindMapNode) : {}
}

function asRawMindMapData(data: unknown): RawMindMapData {
  return data && typeof data === 'object' ? (data as RawMindMapData) : {}
}

export function normalizeNodeFromMindMap(node: unknown): MindMapNode {
  const wrapper = asRawMindMapNode(node)
  const data = wrapper.data ? asRawMindMapData(wrapper.data) : asRawMindMapData(node)
  const children = Array.isArray(wrapper.children)
    ? wrapper.children
    : Array.isArray(data.children)
      ? data.children
      : []
  const rawText = unescapeHtml(String(data.text || data.topic || '未命名节点'))
  const tags = normalizeTags(data.tag)
  const priority = normalizePriority(data.priority) || firstPriorityFromTags(tags) || extractPriority(rawText)
  const hasPreconditionTag = tags.includes(PRECONDITION_TAG) || rawText.trim().startsWith('!')
  const businessTags = tags.filter((tag) => tag !== PRECONDITION_TAG)
  const nextTags = hasPreconditionTag ? [PRECONDITION_TAG, ...businessTags] : businessTags

  return {
    data: {
      text: cleanPreconditionPrefix(priority ? cleanPriorityPrefix(rawText) || rawText : rawText) || rawText,
      ...(typeof data.uid === 'string' ? { uid: data.uid } : {}),
      ...(typeof data.id === 'string' ? { id: data.id } : typeof data.uid === 'string' ? { id: data.uid } : {}),
      ...(priority ? { priority } : {}),
      ...(nextTags.length > 0 ? { tag: nextTags } : {}),
    },
    children: children.map((child) => normalizeNodeFromMindMap(child)),
  }
}

export function updatePriorityInTree(node: MindMapNode, nodeUid: string, priority: Priority): MindMapNode {
  const uid = node.data.uid || node.data.id
  const tags = normalizeTags(node.data.tag).filter((tag) => !normalizePriority(tag))
  const nextNode =
    uid === nodeUid
      ? {
          ...node,
          data: {
            ...node.data,
            text: cleanPreconditionPrefix(cleanPriorityPrefix(node.data.text || '')) || node.data.text,
            priority,
            tag: [priority, ...tags],
          },
        }
      : node

  return {
    ...nextNode,
    children: nextNode.children.map((child) => updatePriorityInTree(child, nodeUid, priority)),
  }
}

export function extractRootData(rawData: unknown) {
  const wrapper = asRawMindMapNode(rawData)
  if (wrapper.root) return wrapper.root
  return rawData
}
