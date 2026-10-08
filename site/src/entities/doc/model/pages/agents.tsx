import { Bullets, DocTable } from '../../ui/prose'
import type { DocPage } from '../types'

// Факты — из docs/local-web.md: Live сам Ollama не запускает, HTTP только на частных адресах.
export const providers: DocPage = {
  slug: 'providers',
  chapter: 'agents',
  short: 'Providers',
  title: 'Bring your',
  em: 'own model.',
  lede: 'Sign in with ChatGPT, use an API key, point at Ollama on your network, or at any OpenAI-compatible API.',
  metaTitle: 'Connect ChatGPT, Claude, Gemini or Ollama — AGI OS Docs',
  sections: [
    {
      id: 'ways-in',
      title: 'Supported ways in',
      summary:
        'ChatGPT sign-in, OpenAI API key, Anthropic API key, Gemini API key, Ollama on your network free, OpenAI-compatible endpoint.',
      content: (
        <>
          <DocTable
            head={['Model', 'Way in', 'Cost']}
            rows={[
              ['ChatGPT', 'Sign-in', 'Your plan'],
              ['OpenAI API', 'API key', 'Per usage'],
              ['Anthropic', 'API key', 'Per usage'],
              ['Gemini', 'API key', 'Per usage'],
              ['Ollama', 'Server on your network', 'Free'],
              ['Compatible endpoint', 'URL and key', 'Depends on the provider'],
            ]}
          />
          <p>
            After you enter a key, the dialog lists that provider&apos;s models. ChatGPT is the only built-in sign-in:
            the terms of Claude and Gemini subscriptions do not allow their sign-in in third-party software, so those
            connect with an API key.
          </p>
        </>
      ),
    },
    {
      id: 'local',
      title: 'Ollama and local servers',
      summary:
        'Live does not run Ollama itself: run it on another computer on your network. Plain HTTP only at loopback, private or link-local addresses, HTTPS elsewhere.',
      content: (
        <Bullets>
          <li>
            The Live system does not run Ollama itself: everything in Live lives in memory, and a model of several GB
            would not fit next to the preview. Run it on another computer on your network.
          </li>
          <li>
            Plain HTTP is accepted only at loopback, private or link-local addresses. Everything else needs HTTPS; for
            Tailscale use <code>tailscale serve</code>.
          </li>
        </Bullets>
      ),
    },
    {
      id: 'keys',
      title: 'Where keys go',
      summary: 'API keys stay in the app memory for the session, never enter the chat and are never copied to the installed system.',
      content: (
        <p>
          API keys stay in the app&apos;s memory for the session. They never enter the chat and are never copied to the
          installed system. Passwords never reach the model.
        </p>
      ),
    },
  ],
}
