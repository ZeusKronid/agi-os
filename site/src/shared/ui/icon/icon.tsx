import type { ComponentProps } from 'react'

type IconProps = Omit<ComponentProps<'svg'>, 'children'>

function Stroke({ children, ...props }: ComponentProps<'svg'>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

export function ArrowDownIcon(props: IconProps) {
  return (
    <Stroke {...props}>
      <path d="M12 4v14M6 12l6 6 6-6" />
    </Stroke>
  )
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <Stroke {...props}>
      <path d="M12 19V5M6 11l6-6 6 6" />
    </Stroke>
  )
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <Stroke {...props}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Stroke>
  )
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Stroke strokeWidth="2" {...props}>
      <path d="M6 9l6 6 6-6" />
    </Stroke>
  )
}

export function CheckIcon(props: IconProps) {
  return (
    <Stroke strokeWidth="2.4" {...props}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Stroke>
  )
}

export function HeartIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M12 20.5s-7-4.3-9.3-8.8C1.2 8.7 2.7 5.3 5.9 5c1.9-.2 3.5.8 4.5 2.2L12 9.3l1.6-2.1c1-1.4 2.6-2.4 4.5-2.2 3.2.3 4.7 3.7 3.2 6.7-2.3 4.5-9.3 8.8-9.3 8.8z" />
    </svg>
  )
}

/** Знак GitHub — Simple Icons (CC0). */
export function GitHubIcon(props: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  )
}
