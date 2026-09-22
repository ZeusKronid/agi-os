# agi-os-web

Публичный сайт AGI OS: SSR на TanStack Start, строгий TypeScript, Tailwind CSS v4, плавный скролл
Lenis, синхронизированный с GSAP ScrollTrigger, архитектура Feature-Sliced Design.

Дизайн-система «Helios» описана в [`DESIGN.md`](DESIGN.md): цвета, шрифты, знак-восход, компоненты,
правила do/don't. Каркас страницы и продуктовые решения — в [`../docs/karkas.md`](../docs/karkas.md) и
[`../docs/PRODUCT-IDEA.md`](../docs/PRODUCT-IDEA.md).

## Стек

| Область    | Пакеты                                                                        |
| ---------- | ----------------------------------------------------------------------------- |
| Фреймворк  | `@tanstack/react-start` 1.168.56 + `@tanstack/react-router` 1.170.38 (SSR)    |
| UI         | React 19.3, только функциональные компоненты                                  |
| Сборка     | Vite 8, `@vitejs/plugin-react` 6                                              |
| Стили      | Tailwind CSS 4.3 через `@tailwindcss/vite`, хелпер `cn` (`clsx` + `tailwind-merge`) |
| Анимации   | `lenis` 1.3 + `gsap` 3.15 (ScrollTrigger)                                     |
| Типы       | TypeScript 7, `strict` + `noUncheckedIndexedAccess`                           |

Требуется Node.js `>=22.12.0` (условие TanStack Start и Vite 8).

Версии `@tanstack/react-start` и `@tanstack/react-router` зафиксированы точно: Start зависит от
строго определённой версии Router, и расхождение даёт две копии роутера в бандле. Обновлять их
нужно вместе.

## Команды

```sh
npm install        # установка зависимостей
npm run dev        # dev-сервер с SSR на http://localhost:3000
npm run build      # production-сборка
npm run preview    # локальный просмотр production-сборки
npm run typecheck  # tsc --noEmit
```

### Генерация route tree — до первого typecheck

`src/routeTree.gen.ts` **генерирует плагин TanStack Start**, руками он не пишется и не правится.
Файл появляется при первом `npm run dev` или `npm run build`. На чистом клоне без этого файла
`npm run typecheck` упадёт на импорте `./routeTree.gen` в `src/router.tsx`, поэтому порядок такой:

```sh
npm install
npm run build      # или npm run dev — создаст src/routeTree.gen.ts
npm run typecheck
```

Сгенерированный файл рекомендуется коммитить (так делают официальные шаблоны TanStack) — тогда
typecheck в CI не зависит от предварительной сборки.

## Структура (Feature-Sliced Design)

```
src/
├── router.tsx               # getRouter() — точка входа роутера для TanStack Start
├── routeTree.gen.ts         # генерируется автоматически
├── app/                     # инициализация приложения
│   ├── routes/              #   тонкие file routes TanStack (только связывают URL со страницей)
│   ├── layouts/             #   RootDocument: <html>, <head>, каркас, монтирование Lenis
│   └── styles/              #   глобальный CSS, токены темы Tailwind (@theme), keyframes
├── pages/                   # страницы: home, not-found
├── widgets/                 # секции страницы: site-header, hero, agents-marquee, feature-grid,
│                            #   faq, get-involved, site-footer
├── features/                # пользовательские возможности: install-demo, scroll-progress
├── entities/                # бизнес-сущности: agent (адаптеры + иконки), tool (инструменты + иконки)
└── shared/                  # переиспользуемый фундамент без бизнес-логики
    ├── config/              #   siteConfig (ссылки, навигация), sectionIds
    ├── lib/cn/              #   cn()
    ├── lib/motion/          #   Lenis + GSAP: mountSmoothScroll, revealOnScroll
    └── ui/                  #   Button, Container, Reveal, Logo, Sunburst, SectionHeading, иконки
```

Каталог маршрутов перенесён в `src/app/routes` опцией `router.routesDirectory` в `vite.config.ts`
(путь задаётся относительно `srcDirectory`, то есть `src`).

### Направление импортов

Слой импортирует только из слоёв **ниже** себя:

```
app → pages → widgets → features → entities → shared
```

- Слайсы одного слоя не импортируют друг друга (`widgets/hero` не знает о `widgets/site-header`).
- Снаружи слайс доступен **только через public API** — его `index.ts`:
  `import { Hero } from '@/widgets/hero'`, но не `'@/widgets/hero/ui/hero'`.
- Внутри слайса — относительные импорты; между слайсами и слоями — алиас `@/` (`src/`).
- В `shared` слайсов нет, public API есть у каждого сегмента/модуля (`@/shared/ui/button`,
  `@/shared/lib/motion`).
- File routes остаются тонкими: `createFileRoute` + компонент страницы из `pages`. Вёрстка, данные
  и логика живут в слоях ниже.

## Анимации: Lenis + GSAP ScrollTrigger

Вся интеграция — в `src/shared/lib/motion`.

**Без `useEffect` / `useLayoutEffect`.** Императивная настройка делается через callback ref
React 19: функция получает DOM-узел при монтировании и возвращает функцию очистки, которую React
вызывает при размонтировании. Все такие функции объявлены на уровне модуля — ссылка стабильна,
React не перезапускает их на ререндерах. В StrictMode (dev) ref вызывается дважды; пара
«настройка → очистка» это корректно переживает.

- `mountSmoothScroll` (подключён в `app/layouts/root-document.tsx`) — создаёт Lenis с
  `autoRaf: false` и ведёт его с тикера GSAP (`gsap.ticker.add` → `lenis.raf`), событие `scroll`
  Lenis вызывает `ScrollTrigger.update` — у скролла и анимаций общие часы. Очистка снимает колбэк
  с тикера, возвращает `lagSmoothing` к значениям GSAP по умолчанию, отписывает слушатель и
  вызывает `lenis.destroy()`.
- `revealOnScroll` (компонент `shared/ui/reveal`) — появление блока при входе во вьюпорт через
  `gsap.matchMedia()`; `revert()` убивает твин и его ScrollTrigger. Контент, уже видимый при
  монтировании, не анимируется — SSR-разметка не мигает при гидрации.
- `features/scroll-progress` — индикатор прогресса на ScrollTrigger со `scrub`; очистка через
  `gsap.context().revert()`.
- Вступление героя — чистый CSS (`motion-safe:animate-rise`): стартует с первой отрисовки, не ждёт
  гидрации.
- `features/install-demo` — окно установщика: ролик из четырёх сцен (слушаю → превью → сборка → установка).
  Callback ref `mountInstallDemo` собирает один GSAP-таймлайн с повтором; состояние сцен — только твины и
  `attr`, без callback'ов, поэтому клик по шагу и ← → честно перематывают. Идёт, пока демо видно, пауза при
  наведении и фокусе; `data-active/done`, `aria-selected` и `inert` сцен обновляются по позиции таймлайна.
  Рамка-прогресс измеряется в пикселях (`pathLength=1`), поэтому после ресайза таймлайн пересобирается.
  SSR-разметка показывает первую сцену. Сцена «слушаю» собрана из общих компонентов `shared/ui/voice`,
  кольцо — `shared/ui/progress-ring`, профиль речи — `shared/lib/motion/speech`.
- `widgets/feature-grid` — визуал «Say it in words»: callback ref `mountWordsVisual` собирает GSAP-таймлайн
  из трёх сцен (волна → кольцо → чипы) с повтором. Идёт, пока визуал виден, встаёт на паузу только при фокусе
  внутри (наведение ролик не останавливает, иначе это читается как фриз), клик по микрофону запускает заново.
  Позиции вылета чипов измеряются из финальной раскладки, поэтому после ресайза и загрузки шрифтов таймлайн
  пересобирается. SSR-разметка показывает третью сцену. Reduced motion здесь намеренно не обрабатывается.
  Плавность: таймлайн собран с `force3D: false`, чтобы 84 столбика волны не становились отдельными слоями
  композитора на время каждого твина; сцены, чипы и кольцо подняты в слой заранее через `will-change`; курсив
  у слов фразы задан статически, чтобы смена `font-style` не вызывала layout посреди анимации; геометрия для
  параллакса читается один раз на вход курсора.
- `widgets/feature-grid` — визуал «Try it live first»: callback ref `mountLiveVisual` гоняет по кругу пять запросов
  (`model/live-requests.ts`): слова фразы проявляются как распознанная речь, затем мини-стол меняется (тёмная тема →
  без панели → другой райсинг → прыгучие окна → назад к светлой). Состояние стола — `data-theme/bar/rice/bouncy` на
  рамке, вся смена вида описана в CSS через `group-data-*`; GSAP нужен только для «bouncy» и отклика на клик по окну.
  Идёт, пока визуал виден; наведение честно ставит цикл на паузу на текущем результате (окна фокусируются под
  курсором), уход курсора продолжает со следующего запроса, клик по строке запроса переводит к следующему сразу.
  SSR-разметка показывает результат последнего запроса (светлый стол), поэтому без JavaScript карточка законченна.
  Reduced motion: слова появляются разом, «bouncy» не подпрыгивает, переходы цвета остаются.
- `widgets/feature-grid` — визуал «What you tried is what you get»: callback ref `mountSameSystemVisual` собирает GSAP-таймлайн
  из трёх сцен, как в «Say it in words»: 01 try (курсор сам нажимает два чипа, превью меняется) → 02 move (миниатюра
  окна, точки бегут по линии к пустому ноутбуку, строки System · Apps · Settings · Files получают «Copied») → 03 yours
  (ноутбук с тем же столом и теми же правками, «Installed», теги «kept»). Идёт, пока визуал виден, встаёт на паузу при
  фокусе внутри; клик по карточке запускает заново, клик по легенде сцен переводит к сцене. Позиции чипов для курсора и
  длина линии переноса измеряются из раскладки, поэтому после ресайза и загрузки шрифтов таймлайн пересобирается.
  SSR-разметка показывает третью сцену. Reduced motion: склейки без сдвига, курсор перескакивает, точки не бегут.
- `widgets/site-header` — `mountHeaderScroll` переключает `data-scrolled` для подложки шапки.
- `widgets/agents-marquee` — CSS-анимация без JavaScript: набор иконок повторён столько раз, что
  половина ленты шире любого монитора, поэтому сдвиг на -50% бесшовен.

**SSR.** Код, обращающийся к `window`, выполняется только внутри callback ref'ов, а они на сервере
не вызываются. На уровне модулей — только импорты и объявления.

**Reduced motion.** При `prefers-reduced-motion: reduce` Lenis не создаётся вовсе (нативный скролл),
reveal-анимации не регистрируются, вступление героя отключено вариантом `motion-safe:`. Keyframes
внутри демо теряют сдвиг и остаются проявлением. Маркиза агентов и автопрокрутка демо продолжают
работать: это осознанное решение, у обеих есть пауза по наведению и фокусу. Смена системной
настройки на лету обрабатывается слушателем media query (он тоже снимается при очистке).

**Tailwind v4 и GSAP.** Утилиты `scale-*`, `translate-*`, `rotate-*` в Tailwind v4 используют
отдельные CSS-свойства (`scale`, `translate`, `rotate`), которые перемножаются с `transform` от
GSAP. Не задавайте их на узле, который трансформирует GSAP; начальное состояние задавайте через
`[transform:...]` или параметры твина.

**Якоря.** Lenis создан с `anchors: true` и сам плавно прокручивает к `<a href="#id">`; отступ под
липкую шапку задаётся через `scroll-mt-*` на секции.

## Правила фронтенда

- Только функциональные компоненты; `useEffect` и `useLayoutEffect` не используются.
- Фронтенд-тесты не пишутся.
- Повторяющуюся разметку выносим в компонент (`shared/ui` или слайс подходящего слоя).

## Ассеты и шрифты

- Geist, Geist Mono и Newsreader подключены с Google Fonts в `app/routes/__root.tsx`.
- `public/fonts/DalekPinpointBold.ttf` — логотипный шрифт (K-Type), используется только в wordmark футера.
  Перед публичным запуском проверьте условия лицензии: http://www.k-type.com/licences
- Иконки агентов и GitHub — контуры Simple Icons (CC0) в `entities/agent/model/marks.ts` и
  `shared/ui/icon`. Товарные знаки принадлежат владельцам и обозначают только совместимость.
- В `shared/config/site.ts` ссылки `download` и `donate` пока ведут на репозиторий (помечены TODO).

## Деплой

Цель деплоя намеренно не выбрана. `vite build` собирает клиент и серверный бандл; для запуска на
Node.js или конкретной платформе нужен адаптер (например, плагин `nitro/vite`) — см.
[Hosting guide](https://tanstack.com/start/latest/docs/framework/react/guide/hosting).
