import { toast } from 'svelte-sonner'

const AUTO_DISMISS_MS = 3000

/** Operation results. Success and info vanish after 3 seconds; errors stay until dismissed with their close button. */
export const notify = {
  success: (message: string) => toast.success(message, { duration: AUTO_DISMISS_MS }),
  info: (message: string) => toast.info(message, { duration: AUTO_DISMISS_MS }),
  error: (message: string) => toast.error(message, { duration: Infinity, closeButton: true }),
}
