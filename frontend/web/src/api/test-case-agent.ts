import { apiUrl } from './client'
import type {
  ChatMessage,
  MindMapChatResult,
  MindMapNode,
  ModuleTestCaseResult,
  TestCaseItem,
  TestCaseModulePlan,
  TestCasePlanResult,
} from '@/types/agent'

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const text = await res.text()
    if (!text) return `HTTP ${res.status}`
    try {
      const parsed = JSON.parse(text) as { error?: unknown }
      if (typeof parsed.error === 'string' && parsed.error) return parsed.error
    } catch {
      return text
    }
    return text
  } catch {
    return `HTTP ${res.status}`
  }
}

async function fetchJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(apiUrl(url), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(await readErrorMessage(res))
  }
  return res.json() as Promise<T>
}

export async function postPlan(requirement: string): Promise<TestCasePlanResult> {
  return fetchJson('/api/test-case-agent/plan', { requirement })
}

export type PostModuleBody = {
  requirement: string
  module: TestCaseModulePlan
  modules: TestCaseModulePlan[]
  /** 与 plan 返回的 mcpDocumentBrief 一致时跳过后端 MCP phase1 */
  mcpDocumentBrief?: string | null
}

export async function postModule(body: PostModuleBody): Promise<ModuleTestCaseResult> {
  return fetchJson('/api/test-case-agent/module', body)
}

export type PostChatBody = {
  messages: ChatMessage[]
  currentMindMap: MindMapNode
}

export async function postChat(body: PostChatBody): Promise<MindMapChatResult> {
  return fetchJson('/api/test-case-agent/chat', body)
}

export type PostExportXmindBody = {
  mindMap: MindMapNode
  testCases?: TestCaseItem[]
  title?: string
}

export async function postExportXmind(body: PostExportXmindBody): Promise<Blob> {
  const res = await fetch(apiUrl('/api/test-case-agent/export-xmind'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(await readErrorMessage(res))
  }
  return res.blob()
}
