import { ref } from 'vue'

/** Label of the last crumb on pages whose name is only known after loading (the run detail page sets it). */
export const crumbTail = ref<string | null>(null)
