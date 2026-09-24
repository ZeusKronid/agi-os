import type { ComponentProps } from 'react'

import { cn } from '@/shared/lib/cn'

export function Container({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('mx-auto w-full max-w-[1228px] px-4 sm:px-6', className)} {...props} />
}
