<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { MindMapNode } from '@/types/agent'
import { EMPTY_MAP } from '@/lib/mindmap-client'
import {
  type ContextMenuState,
  type MindMapConstructor,
  type MindMapInstance,
  type MindMapNodeLike,
  type MindMapRendererNode,
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
const contextMenu = ref<ContextMenuState | null>(null)
const contextMenuRef = ref<HTMLDivElement | null>(null)

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

function hideContextMenu() {
  contextMenu.value = null
}

function showContextMenuAt(clientX: number, clientY: number, node: MindMapRendererNode) {
  const wrapperEl = containerRef.value?.parentElement
  if (!wrapperEl) return

  const wrapperRect = wrapperEl.getBoundingClientRect()
  const menuWidth = 168
  const menuHeight = 72
  const canDelete = !node.isRoot && !node.isGeneralization

  contextMenu.value = {
    x: Math.max(8, Math.min(clientX - wrapperRect.left, wrapperRect.width - menuWidth - 8)),
    y: Math.max(8, Math.min(clientY - wrapperRect.top, wrapperRect.height - menuHeight - 8)),
    canDelete,
    node,
  }
}

function handleNodeContextmenu(e: MouseEvent, node: MindMapRendererNode) {
  e.preventDefault()
  priorityEditor.value = null
  showContextMenuAt(e.clientX, e.clientY, node)
}

function deleteContextNode(removeCurrentOnly: boolean) {
  const menu = contextMenu.value
  if (!menu?.canDelete || !instanceRef.value) return

  hideContextMenu()
  const command = removeCurrentOnly ? 'REMOVE_CURRENT_NODE' : 'REMOVE_NODE'
  instanceRef.value.execCommand?.(command, [menu.node])
}

function handleNodeTagClick(node: MindMapNodeLike, item: MindMapTagItem) {
  hideContextMenu()
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
    instanceRef.value.on?.('node_contextmenu', handleNodeContextmenu)
    instanceRef.value.on?.('node_click', hideContextMenu)
    instanceRef.value.on?.('draw_click', hideContextMenu)
    instanceRef.value.__handlers = {
      handleDataChange,
      handleScale,
      handleNodeTreeRenderEnd,
      handleNodeTagClick,
      handleNodeContextmenu,
      handleHideContextMenu: hideContextMenu,
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

function handleDocumentPointerDown(e: PointerEvent) {
  if (!contextMenu.value) return
  const menuEl = contextMenuRef.value
  if (menuEl?.contains(e.target as Node)) return
  hideContextMenu()
}

onMounted(() => {
  mounted = true
  void initMindMap()
  document.addEventListener('pointerdown', handleDocumentPointerDown)

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
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
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
      instance.off?.('node_contextmenu', handlers.handleNodeContextmenu)
      instance.off?.('node_click', handlers.handleHideContextMenu)
      instance.off?.('draw_click', handlers.handleHideContextMenu)
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
      v-if="contextMenu"
      ref="contextMenuRef"
      class="absolute z-30 min-w-[168px] rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
      :style="{
        left: `${contextMenu.x}px`,
        top: `${contextMenu.y}px`,
      }"
      @contextmenu.prevent
    >
      <button
        type="button"
        class="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-transparent"
        :disabled="!contextMenu.canDelete"
        :title="contextMenu.canDelete ? '删除节点及其子节点' : '根节点不可删除'"
        @click="deleteContextNode(false)"
      >
        <span>删除节点</span>
        <span class="text-xs text-slate-400">Del</span>
      </button>
      <button
        type="button"
        class="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-transparent"
        :disabled="!contextMenu.canDelete"
        :title="contextMenu.canDelete ? '仅删除当前节点，子节点保留' : '根节点不可删除'"
        @click="deleteContextNode(true)"
      >
        <span>仅删除当前节点</span>
        <span class="text-xs text-slate-400">Shift+Del</span>
      </button>
    </div>
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
