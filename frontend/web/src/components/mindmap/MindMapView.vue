<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MindMapNode } from '@/types/agent'
import { EMPTY_MAP } from '@/lib/mindmap-client'
import {
  type MindMapConstructor,
  type MindMapInstance,
  type MindMapNodeLike,
  type MindMapTagItem,
  type Priority,
  type PriorityEditorState,
  TAG_COLORS,
  extractRootData,
  normalizeNodeForMindMap,
  normalizeNodeFromMindMap,
  normalizePriority,
  tagText,
  updatePriorityInTree,
} from './mindmap-view-helpers'

const props = withDefaults(
  defineProps<{
    data?: MindMapNode | null
  }>(),
  { data: null },
)

const emit = defineEmits<{
  'update:data': [MindMapNode]
  'scale-change': [number]
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const instanceRef = ref<MindMapInstance | null>(null)

const renderError = ref<string | null>(null)
const priorityEditor = ref<PriorityEditorState | null>(null)

const priorityChoices = ['P0', 'P1', 'P2', 'P3'] as const

let mounted = false
let changeTimer: ReturnType<typeof setTimeout> | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
const fitTimers: ReturnType<typeof setTimeout>[] = []
let lastSyncedJson = ''
let programmaticUpdate = false
let fitPendingAfterRender = false
let resizeObserver: ResizeObserver | null = null

function currentRoot(): MindMapNode {
  return props.data || EMPTY_MAP
}

function syncScale() {
  const scale = instanceRef.value?.view?.scale
  if (typeof scale === 'number') {
    emit('scale-change', Math.round(scale * 100))
  }
}

function scheduleFit(resetView = false) {
  fitTimers.forEach((t) => clearTimeout(t))
  fitTimers.length = 0

  let didReset = false
  const fit = () => {
    if (!mounted) return
    const instance = instanceRef.value
    if (!instance) return

    try {
      instance.resize?.()
      if (resetView && !didReset) {
        instance.view?.reset?.()
        didReset = true
      }
      instance.view?.fit?.()
      const scale = instance.view?.scale
      if (typeof scale === 'number') {
        emit('scale-change', Math.round(scale * 100))
      }
    } catch {
      /* best-effort */
    }
  }

  requestAnimationFrame(() => {
    requestAnimationFrame(fit)
  })

  fitTimers.push(setTimeout(fit, 120), setTimeout(fit, 320), setTimeout(fit, 640))
}

function applyData(nextData: MindMapNode, resetView = false) {
  if (!instanceRef.value) return

  const mindMapData = normalizeNodeForMindMap(nextData)
  const nextJson = JSON.stringify(mindMapData)
  if (nextJson === lastSyncedJson && !resetView) return

  programmaticUpdate = true
  try {
    if (resetView) {
      fitPendingAfterRender = true
    }
    instanceRef.value.setData?.(mindMapData)
    lastSyncedJson = nextJson
    if (resetView) {
      scheduleFit(true)
    }
  } finally {
    programmaticUpdate = false
  }
}

function changePriority(priority: Priority) {
  const editor = priorityEditor.value
  if (!editor || !instanceRef.value) return

  try {
    const rawData = extractRootData(instanceRef.value.getData?.(true))
    const currentData = normalizeNodeFromMindMap(rawData)
    const nextData = updatePriorityInTree(currentData, editor.nodeUid, priority)
    priorityEditor.value = null
    applyData(nextData)
    emit('update:data', nextData)
  } catch {
    priorityEditor.value = null
  }
}

function handleDataChange() {
  if (programmaticUpdate) return
  if (changeTimer) clearTimeout(changeTimer)
  changeTimer = setTimeout(() => {
    changeTimer = null
    if (!instanceRef.value) return
    try {
      const rawData = extractRootData(instanceRef.value.getData?.(true))
      const nextData = normalizeNodeFromMindMap(rawData)
      lastSyncedJson = JSON.stringify(normalizeNodeForMindMap(nextData))
      emit('update:data', nextData)
    } catch {
      /* transient editor */
    }
  }, 120)
}

function handleScale(scale: number) {
  emit('scale-change', Math.round(scale * 100))
}

function handleNodeTreeRenderEnd() {
  if (!fitPendingAfterRender) return
  fitPendingAfterRender = false
  scheduleFit(true)
}

function handleNodeTagClick(node: MindMapNodeLike, item: MindMapTagItem) {
  const priority = normalizePriority(tagText(item))
  if (!priority) return

  const nodeData = node?.nodeData?.data || node?.data || {}
  const nodeUid =
    typeof nodeData.uid === 'string' ? nodeData.uid : typeof nodeData.id === 'string' ? nodeData.id : ''
  const wrapperEl = containerRef.value?.parentElement
  if (!nodeUid || !wrapperEl) return

  const wrapperRect = wrapperEl.getBoundingClientRect()
  const groupEl = node.group?.node || node.group?.el

  if (groupEl) {
    const bbox = groupEl.getBoundingClientRect()
    if (bbox.width > 0 && bbox.height > 0) {
      priorityEditor.value = {
        x: Math.max(8, bbox.left - wrapperRect.left),
        y: Math.max(8, bbox.bottom - wrapperRect.top + 4),
        currentPriority: priority,
        nodeUid,
      }
      return
    }
  }

  priorityEditor.value = {
    x: Math.max(16, Math.round(wrapperRect.width / 2) - 78),
    y: Math.max(16, Math.round(wrapperRect.height / 2) - 18),
    currentPriority: priority,
    nodeUid,
  }
}

async function initMindMap(retryCount = 0) {
  const el = containerRef.value
  if (!el || instanceRef.value || !mounted) return

  const rect = el.getBoundingClientRect()
  if ((rect.width <= 0 || rect.height <= 0) && retryCount < 12) {
    retryTimer = setTimeout(() => void initMindMap(retryCount + 1), 100)
    return
  }

  try {
    renderError.value = null
    await import('simple-mind-map/dist/simpleMindMap.esm.css')
    const smm = (await import('simple-mind-map')) as unknown as {
      default?: MindMapConstructor
      MindMap?: MindMapConstructor
    }
    const MindMap = smm.default ?? smm.MindMap

    if (!MindMap) {
      throw new Error('simple-mind-map 加载失败')
    }

    if (!mounted || !containerRef.value) return

    containerRef.value.innerHTML = ''
    const initialData = normalizeNodeForMindMap(currentRoot())
    fitPendingAfterRender = true
    instanceRef.value = new MindMap({
      el: containerRef.value,
      data: initialData,
      theme: 'default',
      layout: 'logicalStructure',
      fit: true,
      nodeTextEditZIndex: 1000,
      tagsColorMap: TAG_COLORS,
      maxHistoryCount: 100,
      addHistoryTime: 200,
      mousewheelAction: 'zoom',
      mousewheelZoomActionReverse: false,
      enableCtrlKeyNodeSelection: true,
      enableAutoEnterTextEditWhenKeydown: true,
      openRealtimeRenderOnNodeTextEdit: true,
    })
    lastSyncedJson = JSON.stringify(initialData)

    instanceRef.value.on?.('data_change', handleDataChange)
    instanceRef.value.on?.('scale', handleScale)
    instanceRef.value.on?.('node_tree_render_end', handleNodeTreeRenderEnd)
    instanceRef.value.on?.('node_tag_click', handleNodeTagClick)
    instanceRef.value.__handlers = {
      handleDataChange,
      handleScale,
      handleNodeTreeRenderEnd,
      handleNodeTagClick,
    }

    syncScale()
    scheduleFit(true)
  } catch (error) {
    renderError.value = error instanceof Error ? error.message : '脑图渲染失败'
  }
}

watch(
  () => props.data,
  (next) => {
    if (!instanceRef.value) return
    const nextJson = JSON.stringify(normalizeNodeForMindMap(next || EMPTY_MAP))
    if (nextJson === lastSyncedJson) return
    applyData(next || EMPTY_MAP, true)
  },
  { deep: true },
)

onMounted(() => {
  mounted = true
  void initMindMap()

  nextTick(() => {
    const container = containerRef.value
    if (!container || typeof ResizeObserver === 'undefined') return

    resizeObserver = new ResizeObserver(() => {
      const rect = container.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return

      try {
        instanceRef.value?.resize?.()
      } catch {
        /* layout transition */
      }
    })
    resizeObserver.observe(container)
  })
})

onBeforeUnmount(() => {
  mounted = false
  if (changeTimer) clearTimeout(changeTimer)
  if (retryTimer) clearTimeout(retryTimer)
  fitTimers.forEach((t) => clearTimeout(t))
  fitTimers.length = 0

  resizeObserver?.disconnect()
  resizeObserver = null

  const instance = instanceRef.value
  const container = containerRef.value

  if (instance) {
    const handlers = instance.__handlers
    if (handlers) {
      instance.off?.('data_change', handlers.handleDataChange)
      instance.off?.('scale', handlers.handleScale)
      instance.off?.('node_tree_render_end', handlers.handleNodeTreeRenderEnd)
      instance.off?.('node_tag_click', handlers.handleNodeTagClick)
    }
    instance.destroy?.()
    instanceRef.value = null
  }

  if (container) {
    container.innerHTML = ''
  }
})

const tagColor = computed(() => TAG_COLORS)

defineExpose({
  zoomIn: () => {
    const view = instanceRef.value?.view
    if (!view) return
    view.setScale?.(Math.min((view.scale || 1) + 0.1, 3))
    syncScale()
  },
  zoomOut: () => {
    const view = instanceRef.value?.view
    if (!view) return
    view.setScale?.(Math.max((view.scale || 1) - 0.1, 0.5))
    syncScale()
  },
  fit: () => {
    instanceRef.value?.view?.fit?.()
    syncScale()
  },
  resetLayout: () => {
    instanceRef.value?.execCommand?.('RESET_LAYOUT')
    scheduleFit()
  },
  expandAll: () => {
    instanceRef.value?.execCommand?.('EXPAND_ALL')
  },
  collapseAll: () => {
    instanceRef.value?.execCommand?.('UNEXPAND_ALL', false)
    scheduleFit()
  },
  undo: () => {
    instanceRef.value?.execCommand?.('BACK')
  },
  redo: () => {
    instanceRef.value?.execCommand?.('FORWARD')
  },
  refresh: () => {
    applyData(currentRoot(), true)
  },
})
</script>

<template>
  <div class="relative h-full min-h-0 w-full overflow-hidden">
    <p v-if="renderError" class="absolute left-3 top-3 z-10 text-xs text-red-600">
      {{ renderError }}
    </p>
    <div
      v-if="priorityEditor"
      class="absolute z-20 flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1 shadow-lg"
      :style="{
        left: `${priorityEditor.x}px`,
        top: `${priorityEditor.y}px`,
      }"
    >
      <button
        v-for="p in priorityChoices"
        :key="p"
        type="button"
        class="flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
        :class="priorityEditor.currentPriority === p ? 'bg-slate-100 text-slate-950' : ''"
        :title="`修改为 ${p}`"
        @click="changePriority(p)"
      >
        <span class="h-2 w-2 rounded-full" :style="{ backgroundColor: tagColor[p] }" />
        {{ p }}
      </button>
    </div>
    <div ref="containerRef" class="h-full min-h-0 w-full" />
  </div>
</template>
