import type { Choice } from '../model/route'

interface ChoiceGroupProps<Id extends string> {
  index: string
  legend: string
  name: string
  choices: readonly Choice<Id>[]
  value: Id
  detected?: Id | null
  onChange: (value: Id) => void
}

/** Группа нативных радио-кнопок в виде плиток: стрелки и Tab работают как у браузера. */
export function ChoiceGroup<Id extends string>({
  index,
  legend,
  name,
  choices,
  value,
  detected,
  onChange,
}: ChoiceGroupProps<Id>) {
  return (
    <fieldset>
      <legend className="mb-3 flex items-baseline gap-2.5 font-serif text-[22px] tracking-[-0.012em]">
        <span className="font-mono text-[10.5px] tracking-[0.16em] text-ink-dim">{index}</span>
        {legend}
      </legend>
      <div className="grid gap-2">
        {choices.map((choice) => {
          const tag = choice.id === detected ? 'detected' : choice.tag
          return (
            <label
              key={choice.id}
              className="grid cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-3 rounded-xl bg-surface px-3.5 py-[13px] inset-ring inset-ring-line transition-[box-shadow,background-color] duration-200 hover:inset-ring-line-accent has-checked:bg-accent-soft has-checked:inset-ring-accent has-focus-visible:outline has-focus-visible:outline-offset-4 has-focus-visible:outline-accent"
            >
              <input
                type="radio"
                name={name}
                value={choice.id}
                checked={choice.id === value}
                onChange={() => onChange(choice.id)}
                className="peer sr-only"
              />
              <span
                aria-hidden="true"
                className="grid size-4 place-items-center rounded-full inset-ring-[1.5px] inset-ring-ink-dim after:size-2 after:rounded-full after:bg-accent after:opacity-0 after:transition-opacity after:duration-200 peer-checked:inset-ring-accent peer-checked:after:opacity-100"
              />
              <span>
                <span className="block text-[15.5px] text-ink">{choice.name}</span>
                <span className="block text-[12.5px] text-ink-muted">{choice.note}</span>
              </span>
              {tag && <span className="font-mono text-[9.5px] tracking-[0.14em] text-accent uppercase">{tag}</span>}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
