/** Below this width the three columns do not fit side by side: one view at a time, picked from a bar at the bottom. */
export const NARROW = '(max-width: 1023.98px)'

/** Whether the window is narrow right now, for a handler that acts differently where one view is on screen at a time. */
export const narrow = (): boolean => window.matchMedia?.(NARROW).matches ?? false

/**
 * A screen worked with a finger and nothing else: a phone, a tablet without a mouse. Nothing can rest over
 * a thing there (a tap would open what hovering opens and leave it over the thing tapped), and there are no
 * keys to press. Asked for by name, so that a browser that reports no pointer at all still counts as a desk.
 */
export const touchOnly = (): boolean => window.matchMedia?.('(hover: none) and (pointer: coarse)').matches ?? false
