<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref } from 'vue'
import {
  Download,
  Expand,
  FileArchive,
  Loader2,
  Maximize2,
  Minimize2,
  Redo2,
  RefreshCw,
  Scan,
  Shrink,
  Undo2,
  ZoomIn,
  ZoomOut,
} from 'lucide-vue-next'
import ChatBubblePanel from '@/components/ChatBubblePanel.vue'
import MindMapView from '@/components/mindmap/MindMapView.vue'
import { useTestCaseWorkspace } from '@/composables/useTestCaseWorkspace'
import { countMindMap, normalizeMindMap } from '@/lib/mindmap-client'
import type { MindMapNode } from '@/types/agent'

export type MindMapViewExposed = {
  zoomIn: () => void
  zoomOut: () => void
  fit: () => void
  resetLayout: () => void
  expandAll: () => void
  collapseAll: () => void
  undo: () => void
  redo: () => void
  refresh: () => void
}

const editorPanelRef = ref<HTMLElement | null>(null)
provide('editorPanelRef', editorPanelRef)

const mindMapRef = ref<MindMapViewExposed | null>(null)

const {
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
  sendMessage,
  exportCsv,
  exportXmind,
} = useTestCaseWorkspace()

const mindMapStats = computed(() => countMindMap(mindMap.value))
const isInitialState = computed(() => !hasMindMap.value)
const scalePercent = ref(100)
const isFullscreen = ref(false)

function handleMindMapUpdate(next: MindMapNode) {
  mindMap.value = normalizeMindMap(next)
  testCases.value = []
}

function appendTemplate(content: string) {
  input.value = input.value.trim() ? `${input.value}\n${content}` : content
}

function syncFullscreen() {
  isFullscreen.value = document.fullscreenElement === editorPanelRef.value
  requestAnimationFrame(() => mindMapRef.value?.fit())
}

onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreen)
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreen)
})

async function toggleFullscreen() {
  const node = editorPanelRef.value
  if (!node) return
  try {
    if (document.fullscreenElement === node) {
      await document.exitFullscreen()
    } else {
      await node.requestFullscreen()
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '全屏切换失败'
  }
}
</script>

<template>
  <main
    class="relative box-border flex min-h-0 w-full max-w-full flex-1 flex-col overflow-hidden bg-white"
  >
    <div
      ref="editorPanelRef"
      class="relative flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white"
    >
      <header class="shrink-0 border-b border-slate-200 px-3 py-2.5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="min-w-0">
            <h1 class="text-[15px] font-semibold leading-snug tracking-tight text-slate-900 sm:text-base">
              测试用例脑图
            </h1>
            <p class="mt-0.5 text-xs leading-relaxed text-slate-500 sm:text-[13px]">
              {{
                mindMapStats.caseCount > 0
                  ? `${mindMapStats.categories} 个类别，${mindMapStats.preconditions} 组前置条件，${mindMapStats.caseCount} 条用例`
                  : '输入需求后可生成初始脑图'
              }}
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="撤销"
              aria-label="撤销"
              @click="mindMapRef?.undo()"
            >
              <Undo2 class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="重做"
              aria-label="重做"
              @click="mindMapRef?.redo()"
            >
              <Redo2 class="h-4 w-4" />
            </button>
            <span class="mx-1 hidden h-5 w-px bg-slate-200 sm:inline-block" />
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="缩小"
              aria-label="缩小"
              @click="mindMapRef?.zoomOut()"
            >
              <ZoomOut class="h-4 w-4" />
            </button>
            <span class="w-10 text-center text-xs text-slate-600">{{ scalePercent }}%</span>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="放大"
              aria-label="放大"
              @click="mindMapRef?.zoomIn()"
            >
              <ZoomIn class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="适应画布"
              aria-label="适应画布"
              @click="mindMapRef?.fit()"
            >
              <Scan class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="展开全部"
              aria-label="展开全部"
              @click="mindMapRef?.expandAll()"
            >
              <Expand class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="折叠全部"
              aria-label="折叠全部"
              @click="mindMapRef?.collapseAll()"
            >
              <Shrink class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              title="刷新脑图"
              aria-label="刷新脑图"
              @click="mindMapRef?.refresh()"
            >
              <RefreshCw class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50"
              :title="isFullscreen ? '退出全屏' : '全屏'"
              :aria-label="isFullscreen ? '退出全屏' : '全屏'"
              @click="toggleFullscreen"
            >
              <Minimize2 v-if="isFullscreen" class="h-4 w-4" />
              <Maximize2 v-else class="h-4 w-4" />
            </button>
            <span class="mx-1 hidden h-5 w-px bg-slate-200 sm:inline-block" />
            <button
              type="button"
              class="inline-flex h-9 items-center rounded-md border border-slate-200 bg-white px-2 text-sm hover:bg-slate-50 disabled:opacity-50"
              :disabled="!hasCases"
              @click="exportCsv"
            >
              <Download class="mr-1.5 h-4 w-4" />
              CSV
            </button>
            <button
              type="button"
              class="inline-flex h-9 items-center rounded-md border border-slate-200 bg-white px-2 text-sm hover:bg-slate-50 disabled:opacity-50"
              :disabled="!hasCases || loadingExportXmind"
              @click="exportXmind"
            >
              <Loader2 v-if="loadingExportXmind" class="mr-1.5 h-4 w-4 animate-spin" />
              <FileArchive v-else class="mr-1.5 h-4 w-4" />
              XMind
            </button>
          </div>
        </div>

        <div v-if="hasCases" class="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
          <span
            v-for="p in ['P0', 'P1', 'P2', 'P3'] as const"
            :key="p"
            class="rounded-md border border-slate-200 bg-slate-50 px-2 py-1"
          >
            {{ p }}: {{ mindMapStats.priorities[p] }}
          </span>
        </div>

      </header>

      <!-- 大屏：左侧脑图 ~72%，右侧 AI 栏 ~28%；小屏纵向堆叠 -->
      <div class="flex min-h-0 flex-1 flex-col lg:flex-row lg:overflow-hidden">
        <div class="relative min-h-[min(52vh,560px)] min-w-0 flex-1 bg-slate-50 lg:min-h-0 lg:flex-[1_1_72%]">
          <MindMapView
            ref="mindMapRef"
            :data="mindMap"
            @update:data="handleMindMapUpdate"
            @scale-change="scalePercent = $event"
          />
        </div>
        <ChatBubblePanel
          v-model:input="input"
          variant="sidebar"
          :messages="messages"
          :loading-chat="loadingChat"
          :loading-message="loadingMessage"
          :error="error"
          :has-cases="hasCases"
          :is-initial-state="isInitialState"
          @send="sendMessage"
          @append-template="appendTemplate"
        />
      </div>
    </div>
  </main>
</template>
