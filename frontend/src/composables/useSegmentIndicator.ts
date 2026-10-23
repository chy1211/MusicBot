import {onMounted, onBeforeUnmount, type Ref} from 'vue'

export function useSegmentIndicator(root: Ref<HTMLElement | null>) {
  let resize: ResizeObserver | undefined, mutation: MutationObserver | undefined
  function measure() {
    const element = root.value, active = element?.querySelector<HTMLElement>('[aria-pressed="true"]')
    if (!element || !active || !active.offsetWidth) return
    for (const [key, value] of Object.entries({x: active.offsetLeft, y: active.offsetTop, w: active.offsetWidth, h: active.offsetHeight})) {
      element.style.setProperty('--seg-' + key, value + 'px')
    }
    element.dataset.segmentReady = 'true'
  }
  onMounted(() => {
    if (!root.value) return
    resize = new ResizeObserver(measure); resize.observe(root.value)
    mutation = new MutationObserver(measure)
    mutation.observe(root.value, {subtree: true, childList: true, attributes: true, attributeFilter: ['aria-pressed']})
    measure()
  })
  onBeforeUnmount(() => { resize?.disconnect(); mutation?.disconnect() })
}
