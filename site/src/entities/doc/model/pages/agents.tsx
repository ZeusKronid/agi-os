import { DocTable } from '../../ui/prose'
import type { DocPage } from '../types'

export const providers: DocPage = {
  slug: 'providers',
  chapter: 'agents',
  short: 'Providers',
  title: 'Which agents',
  em: 'connect.',
  lede: 'Sign in with ChatGPT, use an API key, run a local model with Ollama, or point at any OpenAI-compatible endpoint.',
  sections: [
    {
      id: 'ways-in',
      title: 'Supported ways in',
      summary: 'ChatGPT sign-in, OpenAI API key, Anthropic API key, Gemini API key, Ollama local free, OpenAI-compatible endpoint.',
      content: (
        <DocTable
          head={['Agent', 'Way in', 'Cost']}
          rows={[
            ['ChatGPT', 'sign-in', 'Your plan'],
            ['OpenAI API', 'api key', 'Per usage'],
            ['Anthropic', 'api key', 'Per usage'],
            ['Gemini', 'api key', 'Per usage'],
            ['Ollama', 'local', 'Free'],
            ['Compatible endpoint', 'endpoint', 'Depends on the provider'],
          ]}
        />
      ),
    },
    {
      id: 'local',
      title: 'Running fully local',
      summary: 'Ollama runs on the Live system itself. Pick a model that fits in memory alongside a preview kept in memory.',
      content: (
        <p>
          Ollama runs on the Live system itself. Pick a model that fits in memory; the Live system also needs room for
          the preview if you keep it in memory.
        </p>
      ),
    },
  ],
}
