import { InstallRoute } from '@/features/install-route'
import { Container } from '@/shared/ui/container'
import { Sunburst } from '@/shared/ui/sunburst'

// Шапка по общей оси (восход → лейбл → h1 → описание), ниже — пульт маршрута установки.
export function InstallPage() {
  return (
    <Container className="pt-5 pb-[72px] sm:pt-8 sm:pb-28">
      <header className="mb-10 flex flex-col items-center gap-[18px] text-center sm:mb-14">
        <Sunburst variant="mark" className="-mb-1 h-[61px] w-[150px] text-accent opacity-90 motion-safe:animate-rise" />
        <p className="font-mono text-xs tracking-[0.36em] text-ink-muted uppercase motion-safe:animate-rise motion-safe:[animation-delay:60ms]">
          Install
        </p>
        <h1 className="font-serif text-[clamp(36px,4.5vw,60px)] leading-[1.04] tracking-[-0.024em] text-balance motion-safe:animate-rise motion-safe:[animation-delay:120ms]">
          Your <em className="text-accent">route</em> to a live system.
        </h1>
        <p className="max-w-[56ch] text-[16.5px] leading-[1.55] text-ink-muted motion-safe:animate-rise motion-safe:[animation-delay:180ms]">
          Tell us what you’re on and where you’ll boot. The steps rewrite themselves — tick them off as you go. Nothing on
          your disk changes until you confirm the install inside AGI OS.
        </p>
      </header>
      <div className="motion-safe:animate-rise motion-safe:[animation-delay:240ms]">
        <InstallRoute />
      </div>
    </Container>
  )
}
