export interface FaqItem {
  question: string
  answer: string
}

// Ответы опираются на docs/description.md: что подтверждено прогонами в VM, а что пока экспериментально.
export const faqColumns: readonly (readonly FaqItem[])[] = [
  [
    {
      question: 'What is AGI OS?',
      answer:
        'A live Arch Linux environment with an agent inside. You describe the system you want, try it in a preview, and install it when you like it.',
    },
    {
      question: 'How do I get started?',
      answer:
        'Download the ISO and boot it. A page with the agent opens by itself. For now the safest way to start is inside a virtual machine.',
    },
    {
      question: 'Can I really use the system before installing?',
      answer:
        'Yes. The installer builds your system into a preview and opens its desktop in the browser. Launch apps, save files, change settings.',
    },
    {
      question: 'What can I ask for?',
      answer:
        'Desktops, window managers, themes, tools, languages, keyboard layouts, or no desktop at all. Software comes from the official Arch repositories.',
    },
    {
      question: 'Which agents can I connect?',
      answer:
        'ChatGPT sign-in, OpenAI, Anthropic, Gemini, Ollama for local models, and any OpenAI-compatible endpoint.',
    },
  ],
  [
    {
      question: 'Is it free?',
      answer:
        'Yes. AGI OS is open source under the Apache 2.0 license. Your model provider may charge for API usage.',
    },
    {
      question: 'Will it work on my computer?',
      answer:
        'It is tested in virtual machines on 64-bit PCs with UEFI. Installing on real hardware is still experimental, so try a spare machine first.',
    },
    {
      question: 'What happens to the data on my computer?',
      answer:
        'Nothing changes until you confirm the install yourself. The install then replaces everything on the drive you pick, so back up first. Dual boot is not supported yet.',
    },
    {
      question: 'Where do my API keys go?',
      answer:
        "They stay in the app's memory for the session. They are never sent into the chat and never copied to the installed system.",
    },
    {
      question: 'What if something goes wrong?',
      answer:
        'It tells you where it stopped and leaves things as they are. It never retries by wiping again on its own.',
    },
  ],
]
