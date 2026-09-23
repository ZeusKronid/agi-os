/**
 * Учитывать ли системную настройку `prefers-reduced-motion`.
 *
 * Выключено решением владельца сайта: лендинг всегда показывает полную анимацию, даже если система
 * просит reduced motion (например, из-за выключенных анимаций GTK). Все JS-анимации сайта спрашивают
 * о движении только через два запроса ниже, поэтому чтобы вернуть уважение к настройке, достаточно
 * поставить здесь `true` и вернуть два `@custom-variant` в `app/styles/index.css`.
 */
export const RESPECT_REDUCED_MOTION = false

/** Совпадает, когда движение нужно убрать. При `RESPECT_REDUCED_MOTION = false` не совпадает никогда. */
export const REDUCED_MOTION_QUERY = RESPECT_REDUCED_MOTION ? '(prefers-reduced-motion: reduce)' : 'not all'
/** Совпадает, когда движение разрешено. При `RESPECT_REDUCED_MOTION = false` совпадает всегда. */
export const MOTION_SAFE_QUERY = RESPECT_REDUCED_MOTION ? '(prefers-reduced-motion: no-preference)' : 'all'
