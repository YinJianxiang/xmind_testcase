import { computed, ref } from 'vue'
import { postChat, postExportXmind, postModule, postPlan } from '@/api/test-case-agent'
import { downloadTestCasesCsv, extractTestCaseItemsFromMindMap } from '@/lib/export-csv'
import { countMindMap, EMPTY_MAP, mergeModuleMindMap, normalizeMindMap } from '@/lib/mindmap-client'
import type { ChatMessage, MindMapNode, TestCaseItem } from '@/types/agent'

export function useTestCaseWorkspace() {
  const mindMap = ref<MindMapNode>(EMPTY_MAP)
  const testCases = ref<TestCaseItem[]>([])
  const messages = ref<ChatMessage[]>([])
  const input = ref('')
  const loadingChat = ref(false)
  const loadingMessage = ref('')
  const loadingExportXmind = ref(false)
  const error = ref<string | null>(null)

  const hasMindMap = computed(() => mindMap.value.children.length > 0)
  const hasCases = computed(() => countMindMap(mindMap.value).caseCount > 0)

  async function initMindMap(requirementText: string) {
    error.value = null
    try {
      loadingMessage.value = '正在拆解一级模块...'
      const planData = await postPlan(requirementText)

      const modules = Array.isArray(planData.modules) ? planData.modules : []
      const docBrief = planData.mcpDocumentBrief?.trim()
        ? planData.mcpDocumentBrief
        : undefined
      let currentMindMap = normalizeMindMap(planData.mindMap)
      const nextCases: TestCaseItem[] = []
      mindMap.value = currentMindMap
      testCases.value = []

      for (const [index, module] of modules.entries()) {
        loadingMessage.value = `正在生成 ${module.title}（${index + 1}/${modules.length}）...`
        const moduleData = await postModule({
          requirement: requirementText,
          module,
          modules,
          mcpDocumentBrief: docBrief,
        })

        const moduleMindMap = normalizeMindMap(moduleData.mindMap)
        currentMindMap = mergeModuleMindMap(currentMindMap, moduleMindMap)
        if (Array.isArray(moduleData.cases)) {
          nextCases.push(...moduleData.cases)
        }
        mindMap.value = currentMindMap
        testCases.value = [...nextCases]
      }

      messages.value = [
        ...messages.value,
        {
          role: 'assistant',
          content: `${planData.summary}\n\n已按 ${modules.length} 个模块分步生成 ${nextCases.length} 条用例，可继续修改。`,
        },
      ]
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : '未知错误'
      return false
    }
  }

  async function sendMessage() {
    const text = input.value.trim()
    if (loadingChat.value || !text) return

    const userMessage: ChatMessage = { role: 'user', content: text }
    messages.value = [...messages.value, userMessage]
    input.value = ''
    loadingChat.value = true
    error.value = null

    try {
      if (!hasMindMap.value) {
        const generated = await initMindMap(text)
        if (!generated) {
          messages.value = [
            ...messages.value,
            { role: 'assistant', content: '生成失败，请检查配置或稍后重试。' },
          ]
        }
        return
      }

      const nextMessages: ChatMessage[] = [...messages.value]

      const data = await postChat({
        messages: nextMessages,
        currentMindMap: mindMap.value,
      })

      mindMap.value = normalizeMindMap(data.mindMap)
      testCases.value = []
      messages.value = [...messages.value, { role: 'assistant', content: data.assistantReply }]
    } catch (err) {
      error.value = err instanceof Error ? err.message : '未知错误'
      messages.value = [...messages.value, { role: 'assistant', content: '处理失败，请重试。' }]
    } finally {
      loadingMessage.value = ''
      loadingChat.value = false
    }
  }

  function exportCsv() {
    if (!downloadTestCasesCsv(mindMap.value)) {
      error.value = '当前脑图里还没有可导出的测试用例'
    }
  }

  async function exportXmind() {
    if (!hasCases.value) {
      error.value = '当前脑图里还没有可导出的测试用例'
      return
    }

    loadingExportXmind.value = true
    error.value = null
    try {
      const casesPayload =
        testCases.value.length > 0 ? testCases.value : extractTestCaseItemsFromMindMap(mindMap.value)

      const blob = await postExportXmind({
        mindMap: mindMap.value,
        testCases: casesPayload,
        title: mindMap.value.data.text || '测试用例',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${mindMap.value.data.text || '测试用例'}.xmind`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '导出 XMind 失败'
    } finally {
      loadingExportXmind.value = false
    }
  }

  return {
    mindMap,
    testCases,
    messages,
    input,
    loadingChat,
    loadingMessage,
    loadingExportXmind,
    error,
    hasMindMap,
    hasCases,
    initMindMap,
    sendMessage,
    exportCsv,
    exportXmind,
  }
}
