import type { ComponentProps } from 'react'

import { cn } from '@/shared/lib/cn'

type ButtonVariant = 'primary' | 'outline'
type ButtonSize = 'md' | 'sm'

interface ButtonStyleOptions {
  variant?: ButtonVariant
  size?: ButtonSize
  className?: string
}

const baseStyles =
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[7px] transition-[background-color,box-shadow,scale] duration-150 ease-out-strong active:scale-[0.97] [&_svg]:size-[15px] [&_svg]:transition-[translate] [&_svg]:duration-200'

const variantStyles: Record<ButtonVariant, string> = {
  // Единственная залитая кнопка системы: коралл + моноширинный текст.
  primary:
    'bg-accent font-mono font-medium tracking-[0.02em] text-on-accent hover:bg-accent-hover active:bg-accent-deep hover:[&_svg]:translate-y-0.5',
  // Вторичное действие — линия вместо заливки, текст антиквой.
  outline:
    'font-serif text-ink inset-ring inset-ring-line-accent hover:inset-ring-accent hover:[&_svg]:translate-x-0.5',
}

const sizeStyles: Record<ButtonSize, Record<ButtonVariant, string>> = {
  md: { primary: 'h-12 px-7 text-[14.5px]', outline: 'h-12 px-11 text-lg' },
  sm: { primary: 'h-10 px-5 text-[13.5px]', outline: 'h-10 px-6 text-base' },
}

/** Классы кнопки — для элементов, которые не являются `<a>` (например, router `Link`). */
export function buttonStyles({
  variant = 'primary',
  size = 'md',
  className,
}: ButtonStyleOptions = {}): string {
  return cn(baseStyles, variantStyles[variant], sizeStyles[size][variant], className)
}

interface ButtonLinkProps extends ComponentProps<'a'> {
  variant?: ButtonVariant
  size?: ButtonSize
}

export function ButtonLink({ variant, size, className, ...props }: ButtonLinkProps) {
  return <a className={buttonStyles({ variant, size, className })} {...props} />
}
