"""English wording for engine messages shown by the native installer.

The engine (controller, providers, worker, system, domain) is shared with the Russian Live website,
so its messages stay Russian there. The native installer speaks English and translates the
messages it knows; anything unknown is shown as is.
"""

import re


EXACT = {
    # worker.py: progress and results
    "Проверяю репозитории и пакеты до изменения диска…": "Checking repositories and packages before touching the disk…",
    "Шифрую корневой раздел (LUKS2)…": "Encrypting the root partition (LUKS2)…",
    "Устанавливаю базовую систему…": "Installing the base system…",
    "Настраиваю загрузку, пользователя, сеть и выбранное окружение…": "Setting up boot, your user, the network and your desktop…",
    "Запись и настройка завершены. Загрузка без ISO ещё не проверена.":
        "Written and set up. Booting without the ISO is not checked yet.",
    "Установка остановлена. Диск мог быть частично изменён.": "Installation stopped. The disk may be partly changed.",
    "Установка остановлена; на диске осталась частичная установка.":
        "Installation stopped. A partial installation is left on the disk.",
    "Остановлено до изменения диска": "Stopped before the disk was changed",
    "Установка прервана внутренней ошибкой. Результат не считается готовым.":
        "The installation hit an internal error. The result is not usable.",
    "Файл настроек выходит за пределы установленной системы": "A settings file points outside the installed system",
    "Запись дисков разрешена только в загруженной live-системе AGI OS": "Disks can be written only from the booted AGI OS live system",
    "Неизвестный запрос установки": "Unknown installation request",
    "Конфигурация изменилась после подтверждения": "The configuration changed after you confirmed it",
    "Диск изменился после подтверждения; запись отменена": "The disk changed after you confirmed it; nothing was written",
    "Для BIOS требуется загрузчик GRUB": "BIOS computers need the GRUB bootloader",
    "Введите пароль длиной от 8 до 256 символов без переносов строк": "Enter a password of 8 to 256 characters without line breaks",
    "Пароль шифрования: от 8 до 512 символов без переносов строк": "Encryption password: 8 to 512 characters without line breaks",
    "Выбранная локаль недоступна": "The selected locale is not available",
    "Каталог установки занят предыдущей операцией; нужна проверка её состояния":
        "A previous operation still holds the install directory; check its state first",
    "Не удалось отключить разделы установки. Не выключайте VM до проверки mount.":
        "Could not unmount the install partitions. Keep the VM running until you check mount.",
    "Не удалось закрыть зашифрованный раздел после установки.": "Could not close the encrypted partition after installing.",
    "Идентификатор диска изменился до записи": "The disk ID changed before writing",
    "Для графической сессии не включён дисплейный менеджер": "No display manager is enabled for the graphical session",
    "Проверка установленных пакетов не пройдена": "The installed packages did not pass the check",
    "Установочный движок запускается только в live-системе AGI OS": "The install engine runs only in the AGI OS live system",
    "Запрос слишком большой": "The request is too large",
    # controller.py
    "Изменение конфигурации во время установки недоступно": "The configuration can’t change during installation",
    "Введите сообщение длиной до 16000 символов": "Write a message of up to 16000 characters",
    "Диалог слишком длинный. Сохраните согласованные требования и начните новое подключение.":
        "The conversation is too long. Note what you agreed on and start a new connection.",
    "В BIOS нужен GRUB": "BIOS needs GRUB",
    "Предложение требует дополнительных уточнений. Напишите, что нужно изменить; запись диска не начиналась.":
        "The proposal needs more detail. Say what to change; nothing has been written to disk.",
    # providers.py, chatgpt.py, bridge.py
    "Модель вернула неполный ответ. Повторите запрос или выберите другую модель.":
        "The model returned an incomplete reply. Send it again or pick another model.",
    "Неизвестный API-провайдер": "Unknown API provider",
    "Укажите базовый адрес API без ключей, параметров и учётных данных": "Enter the API base URL without keys, parameters or credentials",
    "Для удалённого провайдера требуется HTTPS": "A remote provider needs HTTPS",
    "Введите API-ключ в отдельном поле подключения": "Enter your API key in the key field",
    "Ответ провайдера слишком большой": "The provider’s response is too large",
    "Не удалось получить ответ. Проверьте сеть и адрес API.": "No response. Check the network and the API URL.",
    "Выберите модель": "Pick a model",
    "Провайдер не завершил ответ; конфигурация не изменена": "The provider didn’t finish the reply; the configuration is unchanged",
    "Модель не завершила структурированный ответ": "The model didn’t finish its structured reply",
    "Неоднозначный ответ модели": "The model’s reply was ambiguous",
    "Локальная модель не завершила ответ": "The local model didn’t finish the reply",
    "Модель не завершила ответ": "The model didn’t finish the reply",
    "Для входа через ChatGPT нужны пакеты bubblewrap и openai-codex": "ChatGPT sign-in needs the bubblewrap and openai-codex packages",
    "Не удалось запустить службу ChatGPT": "Could not start the ChatGPT service",
    "Соединение ChatGPT закрыто. Подключитесь снова через «Сменить провайдера».":
        "The ChatGPT connection closed. Connect again with “Change model”.",
    "Истекло время ожидания ChatGPT": "ChatGPT timed out",
    "Служба ChatGPT завершилась. Проверьте поддержку bubblewrap и версию Codex.":
        "The ChatGPT service stopped. Check bubblewrap support and the Codex version.",
    "Аккаунт на хосте изменился; перезапустите мост": "The host account changed; restart the bridge",
    "Истекло время запроса ChatGPT": "The ChatGPT request timed out",
    "Вход в ChatGPT не завершён": "ChatGPT sign-in didn’t finish",
    "Время входа в ChatGPT истекло": "ChatGPT sign-in timed out",
    "Выберите модель ChatGPT": "Pick a ChatGPT model",
    "ChatGPT не завершил ответ": "ChatGPT didn’t finish the reply",
    "Ответ ChatGPT занял слишком много времени": "ChatGPT took too long to reply",
    "Мост отключён": "The bridge is off",
    "Диалог слишком большой для моста": "The conversation is too large for the bridge",
    "Мост не получил ответ. Проверьте вход Codex на хосте, сеть и лимиты.":
        "The bridge got no reply. Check the Codex sign-in on the host, the network and limits.",
    "Канал моста недоступен. Переподключитесь или перезапустите тестовую VM.":
        "The bridge channel is unavailable. Reconnect or restart the test VM.",
    "Истекло время ожидания моста": "The bridge timed out",
    "Мост вернул неверный список моделей": "The bridge returned an invalid model list",
    "Подключение отменено": "Connection cancelled",
    # system.py
    "Выбранный диск недоступен для установки. Обновите список дисков.": "The selected disk can’t be used. Refresh the disk list.",
    "Каталог пакетов пуст. Проверьте сеть и повторите запрос: доступность пакетов пока не подтверждена.":
        "The package catalog is empty. Check the network and try again: packages are not confirmed yet.",
    "Демонстрационный диск": "Demo disk",
    # domain.py: validation of the model's proposal
    "Провайдер вернул ответ неизвестного формата. Повторите запрос.": "The provider replied in an unknown format. Send it again.",
    "Некорректная конфигурация в ответе модели": "The model’s reply has an invalid configuration",
    "Конфигурация неполна или содержит неизвестные поля": "The configuration is incomplete or has unknown fields",
    "Некорректное имя графической сессии": "Invalid graphical session name",
    "Некорректный путь диска": "Invalid disk path",
    "Для этой файловой системы пока нет проверенного обработчика": "This filesystem is not supported yet",
    "Для этого загрузчика пока нет обработчика": "This bootloader is not supported yet",
    "Выберите имя обычного пользователя, отличное от системных аккаунтов": "Choose a regular user name, not a system account",
    "Некорректное имя компьютера": "Invalid hostname",
    "Нужна локаль вида ru_RU.UTF-8 или en_US.UTF-8": "Use a locale like en_US.UTF-8",
    "Неизвестный часовой пояс": "Unknown time zone",
    "Укажите XKB-раскладки, например us и ru": "List XKB layouts, for example us and de",
    "Нужен список требований для проверки готовой системы": "A list of requirements is needed to check the finished system",
    "Некорректное имя пакета": "Invalid package name",
    "Некорректное имя службы": "Invalid service name",
    "Слишком много файлов настроек": "Too many settings files",
    "Некорректный файл настроек": "Invalid settings file",
    "Нужен относительный путь без ..": "Use a relative path without ..",
    "Настройки пользователя должны находиться в .config": "User settings must live in .config",
    "Этот системный файл управляется установочным движком": "The install engine manages this system file",
    "Некорректное содержимое файла настроек": "Invalid settings file content",
    "Повторяющиеся файлы настроек": "Duplicate settings files",
}

HTTP = {
    "Ключ не принят": "Key not accepted",
    "Нет доступа": "Access denied",
    "API или модель не найдены": "API or model not found",
    "Достигнут лимит запросов или средств": "Request or spending limit reached",
    "Ошибка провайдера": "Provider error",
}

PATTERNS = [
    (r"Создаю согласованные разделы на (.+)", lambda m: f"Creating the agreed partitions on {m[1]}"),
    (r"Устанавливаю выбранные пакеты \((\d+) из (\d+)\)…", lambda m: f"Installing your packages ({m[1]} of {m[2]})…"),
    (r"Повторяю загрузку пакетов \(попытка (\d+) из (\d+)\)…", lambda m: f"Retrying the package download (attempt {m[1]} of {m[2]})…"),
    (r"Истекло время операции (.+)", lambda m: f"Timed out: {m[1]}"),
    (r"Ошибка (\S+) \(код (-?\d+)\)(.*)", lambda m: f"{m[1]} failed (code {m[2]}){m[3]}"),
    (r"В live-системе отсутствует инструмент: (.+)", lambda m: f"The live system is missing a tool: {m[1]}"),
    (r"Указанная графическая сессия не установлена: (.+)", lambda m: f"The graphical session is not installed: {m[1]}"),
    (r"Не выполнена проверка: (.+)", lambda m: f"Check failed: {m[1]}"),
    (r"Пакеты не найдены в core/extra: (.+)", lambda m: f"Packages not found in core/extra: {m[1]}"),
    (r"Некорректное поле: (.+)", lambda m: f"Invalid field: {m[1]}"),
    (r"Некорректный список: (.+)", lambda m: f"Invalid list: {m[1]}"),
    (r"Ищу пакеты: (.+)", lambda m: f"Looking up packages: {m[1]}"),
    (r"Уточняю конфигурацию: (.+)", lambda m: f"Refining the configuration: {english(m[1])}"),
    (r"ChatGPT не выполнил запрос (.+)", lambda m: f"ChatGPT didn’t complete the request {m[1]}"),
    (r"(.+) \(HTTP (\d+)\)", lambda m: f"{HTTP.get(m[1], m[1])} (HTTP {m[2]})"),
]


def english(text):
    """English wording of an engine message; unknown messages come back unchanged."""
    if text in EXACT:
        return EXACT[text]
    for pattern, render in PATTERNS:
        match = re.fullmatch(pattern, text, re.S)
        if match:
            return render(match)
    return text
