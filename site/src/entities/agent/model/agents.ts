import type { AgentMark } from './marks'

export interface Agent {
  id: string
  label: string
  mark: AgentMark
}

/** Только те подключения, для которых в установщике есть адаптер (`installer/providers.py`, `chatgpt.py`). */
export const agents: readonly Agent[] = [
  { id: 'chatgpt', label: 'ChatGPT', mark: 'openai' },
  { id: 'anthropic', label: 'Anthropic', mark: 'anthropic' },
  { id: 'claude', label: 'Claude', mark: 'claude' },
  { id: 'gemini', label: 'Gemini', mark: 'gemini' },
  { id: 'ollama', label: 'Ollama', mark: 'ollama' },
  { id: 'openai-api', label: 'OpenAI API', mark: 'openai' },
  { id: 'compatible', label: 'OpenAI‑compatible', mark: 'compatible' },
]
