<script setup lang="ts">
import {
  computed,
  inject,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
  type Ref,
} from 'vue'
import { Loader2, MessageSquare, Send, X } from 'lucide-vue-next'
import type { ChatMessage } from '@/types/agent'
import { REQUIREMENT_TEMPLATES } from '@/data/requirement-templates'
import {
  CHAT_BUBBLE_DRAG_THRESHOLD,
  CHAT_BUBBLE_MARGIN,
  CHAT_BUBBLE_PANEL_HEIGHT,
  CHAT_BUBBLE_PANEL_WIDTH,
  CHAT_BUBBLE_SIZE,
  CHAT_BUBBLE_TOP,
} from '@/lib/chat-bubble-constants'

const _panelRef = inject<Ref<HTMLElement | null> | undefined>('editorPanelRef')
if (_panelRef == null) {
  throw new Error('ChatBubblePanel: inject editorPanelRef from App')
}
const editorPanelRef: Ref<HTMLElement | null> = _panelRef

const props = defineProps<{
  messages: ChatMessage[]
  loadingChat: boolean
  loadingMessage: string
  error: string | null
  hasCases: boolean
  isInitialState: boolean
}>()

const input = defineModel<string>('input', { required: true })

const emit = defineEmits<{
  send: []
  'append-template': [string]
}>()

const isChatOpen = ref(true)
const chatBubblePosition = ref({ x: 0, y: CHAT_BUBBLE_TOP })
const messagesEndRef = ref<HTMLElement | null>(null)
const hasPlacedBubble = ref(false)
const suppressBubbleClick = ref(false)

type DragState = {
  offsetX: number
  offsetY: number
  startX: number
  startY: number
  width: number
  height: number
  moved: boolean
}

let dragState: DragState | null = null
let resizeObserver: ResizeObserver | null = null

function getBubbleDimensions(open: boolean) {
  const container = editorPanelRef.value
  if (!open) {
    return { width: CHAT_BUBBLE_SIZE, height: CHAT_BUBBLE_SIZE }
  }

  const maxWidth = container
    ? Math.max(CHAT_BUBBLE_SIZE, container.clientWidth - CHAT_BUBBLE_MARGIN * 2)
    : CHAT_BUBBLE_PANEL_WIDTH
  const maxHeight = container
    ? Math.max(220, container.clientHeight - CHAT_BUBBLE_MARGIN * 2)
    : CHAT_BUBBLE_PANEL_HEIGHT

  return {
    width: Math.min(CHAT_BUBBLE_PANEL_WIDTH, maxWidth),
    height: Math.min(CHAT_BUBBLE_PANEL_HEIGHT, maxHeight),
  }
}

function clampBubblePosition(
  next: { x: number; y: number },
  panelWidth = CHAT_BUBBLE_SIZE,
  panelHeight = CHAT_BUBBLE_SIZE,
) {
  const container = editorPanelRef.value
  if (!container) return next

  const maxX = Math.max(CHAT_BUBBLE_MARGIN, container.clientWidth - panelWidth - CHAT_BUBBLE_MARGIN)
  const maxY = Math.max(CHAT_BUBBLE_MARGIN, container.clientHeight - panelHeight - CHAT_BUBBLE_MARGIN)

  return {
    x: Math.min(Math.max(CHAT_BUBBLE_MARGIN, next.x), maxX),
    y: Math.min(Math.max(CHAT_BUBBLE_MARGIN, next.y), maxY),
  }
}

function getDefaultBubblePosition(open: boolean) {
  const container = editorPanelRef.value
  const { width, height } = getBubbleDimensions(open)

  if (!container) {
    return { x: 20, y: CHAT_BUBBLE_TOP }
  }

  return clampBubblePosition(
    {
      x: container.clientWidth - width - 20,
      y: CHAT_BUBBLE_TOP,
    },
    width,
    height,
  )
}

function updateBubblePosition(clientX: number, clientY: number) {
  const container = editorPanelRef.value
  if (!dragState || !container) return

  const containerRect = container.getBoundingClientRect()
  const nextPosition = clampBubblePosition(
    {
      x: clientX - containerRect.left - dragState.offsetX,
      y: clientY - containerRect.top - dragState.offsetY,
    },
    dragState.width,
    dragState.height,
  )

  if (!dragState.moved) {
    const deltaX = clientX - dragState.startX
    const deltaY = clientY - dragState.startY
    if (Math.hypot(deltaX, deltaY) >= CHAT_BUBBLE_DRAG_THRESHOLD) {
      dragState.moved = true
      suppressBubbleClick.value = true
    }
  }

  chatBubblePosition.value = nextPosition
}

function handleWindowMouseMove(event: MouseEvent) {
  updateBubblePosition(event.clientX, event.clientY)
}

function stopDraggingBubble() {
  dragState = null
  window.removeEventListener('mousemove', handleWindowMouseMove)
  window.removeEventListener('mouseup', stopDraggingBubble)
}

function startDraggingBubble(event: MouseEvent) {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()

  dragState = {
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
    startX: event.clientX,
    startY: event.clientY,
    width: rect.width,
    height: rect.height,
    moved: false,
  }

  window.addEventListener('mousemove', handleWindowMouseMove)
  window.addEventListener('mouseup', stopDraggingBubble)
}

function handleBubbleTriggerClick() {
  if (suppressBubbleClick.value) {
    suppressBubbleClick.value = false
    return
  }
  isChatOpen.value = true
}

function handleInputKeyDown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  if ((event as KeyboardEvent & { isComposing?: boolean }).isComposing) return
  event.preventDefault()
  emit('send')
}

const bubbleDimensions = ref(getBubbleDimensions(isChatOpen.value))

watch(isChatOpen, () => {
  bubbleDimensions.value = getBubbleDimensions(isChatOpen.value)
  if (!hasPlacedBubble.value) return
  const { width, height } = getBubbleDimensions(isChatOpen.value)
  chatBubblePosition.value = clampBubblePosition(chatBubblePosition.value, width, height)
  bubbleDimensions.value = { width, height }
})

function syncBubbleOnResize() {
  const { width, height } = getBubbleDimensions(isChatOpen.value)

  if (!hasPlacedBubble.value) {
    hasPlacedBubble.value = true
    chatBubblePosition.value = getDefaultBubblePosition(isChatOpen.value)
    bubbleDimensions.value = { width, height }
    return
  }

  chatBubblePosition.value = clampBubblePosition(chatBubblePosition.value, width, height)
  bubbleDimensions.value = { width, height }
}

watch(
  () => editorPanelRef.value,
  (el) => {
    resizeObserver?.disconnect()
    resizeObserver = null
    if (!el || typeof ResizeObserver === 'undefined') return

    syncBubbleOnResize()
    resizeObserver = new ResizeObserver(() => {
      syncBubbleOnResize()
    })
    resizeObserver.observe(el)
  },
  { immediate: true },
)

watch(
  () => [props.loadingChat, props.messages.length] as const,
  () => {
    nextTick(() => {
      messagesEndRef.value?.scrollIntoView({ block: 'end' })
    })
  },
)

const canSend = computed(() => !props.loadingChat && input.value.trim().length > 0)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  stopDraggingBubble()
})

</script>

<template>
  <template v-if="isChatOpen">
    <div
      class="absolute z-30 flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200/90 bg-white/95 shadow-2xl backdrop-blur"
      :style="{
        left: `${chatBubblePosition.x}px`,
        top: `${chatBubblePosition.y}px`,
        width: `${bubbleDimensions.width}px`,
        height: `${bubbleDimensions.height}px`,
      }"
    >
      <div
        class="flex cursor-move select-none items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/95 px-3 py-2.5"
        @mousedown="startDraggingBubble"
      >
        <div class="flex min-w-0 items-center gap-2">
          <MessageSquare class="h-4 w-4 shrink-0 text-slate-700" />
          <span class="truncate text-sm font-semibold text-slate-900">AI 对话</span>
          <span class="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-500">
            {{ loadingChat ? '处理中' : hasCases ? '可编辑' : '待生成' }}
          </span>
        </div>
        <button
          type="button"
          class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-100"
          title="收起对话"
          @mousedown.stop
          @click="isChatOpen = false"
        >
          <X class="h-4 w-4" />
        </button>
      </div>

      <div class="flex min-h-0 min-w-0 flex-1 flex-col">
        <div class="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-slate-50 px-3 py-3">
          <div class="flex flex-col gap-3">
            <template v-if="messages.length === 0">
              <div class="rounded-lg border border-dashed border-slate-200 bg-white p-3 text-sm leading-6 text-slate-500">
                先输入需求并发送，AI 会生成初始测试用例脑图；生成后可以继续通过对话局部修改。
              </div>
            </template>
            <template v-else>
              <div
                v-for="(msg, idx) in messages"
                :key="`${msg.role}-${idx}`"
                class="flex min-w-0"
                :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
              >
                <div
                  :class="
                    msg.role === 'user'
                      ? 'max-w-[88%] rounded-lg rounded-br-sm bg-blue-600 px-3 py-2 text-white shadow-sm'
                      : 'max-w-[88%] rounded-lg rounded-bl-sm border border-slate-200 bg-white px-3 py-2 text-slate-800 shadow-sm'
                  "
                >
                  <p
                    :class="
                      msg.role === 'user' ? 'mb-1 text-[11px] text-blue-100' : 'mb-1 text-[11px] text-slate-500'
                    "
                  >
                    {{ msg.role === 'user' ? '你' : 'AI' }}
                  </p>
                  <p class="whitespace-pre-wrap break-words text-sm leading-6">{{ msg.content }}</p>
                </div>
              </div>
            </template>
            <div v-if="loadingChat" class="flex justify-start">
              <div
                class="max-w-[88%] rounded-lg rounded-bl-sm border border-slate-200 bg-white px-3 py-2 text-sm text-slate-500 shadow-sm"
              >
                <Loader2 class="mr-2 inline h-4 w-4 animate-spin" />
                {{
                  loadingMessage ||
                  (isInitialState ? '正在分析需求、生成测试用例...' : '正在按你的指令更新脑图...')
                }}
              </div>
            </div>
            <div ref="messagesEndRef" />
          </div>
        </div>

        <div class="min-w-0 border-t border-slate-200 bg-white p-2.5">
          <textarea
            v-model="input"
            class="min-h-[88px] w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-slate-400"
            :placeholder="
              isInitialState
                ? '输入需求内容，按 Enter 发送；Shift+Enter 换行'
                : '输入修改指令，例如：删除某分支，新增 3 条边界用例'
            "
            @keydown="handleInputKeyDown"
          />
          <p v-if="error" class="mt-2 text-xs text-red-600">{{ error }}</p>
          <div class="mt-2 flex items-center gap-2">
            <div class="flex min-w-0 flex-1 gap-1.5 overflow-x-auto pb-1">
              <button
                v-for="item in REQUIREMENT_TEMPLATES"
                :key="item.label"
                type="button"
                class="shrink-0 rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                @click="emit('append-template', item.content)"
              >
                {{ item.label }}
              </button>
            </div>
            <button
              type="button"
              class="inline-flex h-9 shrink-0 items-center rounded-md bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              :disabled="!canSend"
              @click="emit('send')"
            >
              <Loader2 v-if="loadingChat" class="mr-2 h-4 w-4 animate-spin" />
              <Send v-else class="mr-2 h-4 w-4" />
              发送
            </button>
          </div>
        </div>
      </div>
    </div>
  </template>
  <button
    v-else
    type="button"
    class="absolute z-30 inline-flex h-11 w-11 items-center justify-center rounded-full border border-slate-900/10 bg-slate-900 text-white shadow-2xl hover:bg-slate-800"
    :style="{ left: `${chatBubblePosition.x}px`, top: `${chatBubblePosition.y}px` }"
    title="展开 AI 对话"
    @mousedown="startDraggingBubble"
    @click="handleBubbleTriggerClick"
  >
    <MessageSquare class="h-5 w-5" />
  </button>
</template>
