import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Склеивает условные классы и разрешает конфликты Tailwind-утилит. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
