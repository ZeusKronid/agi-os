#!/usr/bin/env python3
"""Generate a self-contained QA report from externally captured screenshots."""
import base64
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
folder = ROOT / 'docs/test-results/2026-09-17-live-web'
evidence = json.loads((folder/'evidence.json').read_text())
figures = []
for item in evidence['screenshots']:
    path = folder/'screenshots'/item['file']
    image = base64.b64encode(path.read_bytes()).decode()
    figures.append(f'<section><h2>{html.escape(item["title"])}</h2><p>{html.escape(item["text"])}</p><img src="data:image/png;base64,{image}" alt="{html.escape(item["title"])}"></section>')
checks = ''.join(f'<li>{html.escape(check)}</li>' for check in evidence['checks'])
limits = ''.join(f'<li>{html.escape(note)}</li>' for note in evidence['limits'])
page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AGIOS · Live boot → сайт → VM</title><style>
*{box-sizing:border-box}body{margin:0;background:#0c1017;color:#dce3ed;font:16px/1.65 system-ui,sans-serif}main{max-width:1340px;margin:auto;padding:45px 30px}header{margin-bottom:38px}.label{color:#b0f0cb;font-size:12px;letter-spacing:2px}h1{font-size:clamp(28px,4vw,48px);line-height:1.15;max-width:1000px}h2{font-size:24px}p{color:#a6b4c5;max-width:1000px}section{margin:40px 0}img{display:block;width:100%;height:auto;border:1px solid #344153;border-radius:12px;background:#000}.flow{display:flex;gap:16px;align-items:center;flex-wrap:wrap;background:#121c28;border:1px solid #344153;border-radius:12px;padding:22px}.flow strong{color:#b0f0cb}.flow span{color:#8497ac}.grid{display:grid;grid-template-columns:1fr 1fr;gap:32px}.card{background:#121a25;border:1px solid #293a4c;border-radius:12px;padding:20px 28px}li{margin:10px 0}code{font-size:14px}footer{border-top:1px solid #344153;padding-top:24px;color:#8497ac}@media(max-width:750px){main{padding:24px 16px}.grid{grid-template-columns:1fr}}
</style><main><header><div class="label">AGIOS · ПРОВЕРКА LIVE-ПРОТОТИПА · 17 СЕНТЯБРЯ 2026</div><h1>Live boot. Сайт на localhost. Система в виртуальной машине.</h1><p>Снимки реального запуска. Этот HTML содержит изображения внутри себя: ISO и приложение запускать для просмотра отчёта не нужно.</p></header><div class="flow"><strong>Внешняя VM для теста</strong><span>→</span><strong>AGIOS Live + Firefox / localhost</strong><span>→</span><strong>Внутренняя VM + Guacamole</strong></div><p>Внешняя VM заменяет физический компьютер только при тестировании. Сайт, агент, контроллер и Guacamole работают внутри Live-среды.</p>'''
page += f'<div class="grid"><section class="card"><h2>Проверено</h2><ul>{checks}</ul></section><section class="card"><h2>Границы проверки</h2><ul>{limits}</ul></section></div>'
page += '\n'.join(figures)
page += '<footer>Артефакт: <code>out/agi-os-live-web.iso</code>. Снимки сделаны внешними средствами проверки; функции скриншотов в интерфейсе AGIOS нет.</footer></main></html>'

legacy=page.split('<main>',1)[1].rsplit('</main>',1)[0]
style=page.split('<style>',1)[1].split('</style>',1)[0]
root=ROOT/'docs/test-results/2026-09-17-hyprland'
sections=[
('02-preview.png','1. Hyprland в превью','Реальный Wayland-сеанс внутри вложенной VM: Waybar, foot и Thunar. Создан файл AGIOS-PREVIEW-PERSISTENCE.txt. Ошибок Lua нет. Тема foot исправлена внутри превью: в текущей версии нужна секция colors-dark.'),
('03-launcher.png','2. Запуск приложений','Super+D открывает wofi, Super+E — Thunar. Экран и ввод передаются через Apache Guacamole.'),
('04-browser.png','3. Сайт внутри Live','Firefox, агент, Guacamole и управление внутренней VM работают внутри внешней Live-машины. На компьютере разработчика сайт не запускается.'),
('05-final-confirm.png','4. Отдельное подтверждение конечного диска','Превью штатно выключено. Выбран только тестовый диск AGIOS_TARGET на 40 ГиБ. Рабочее хранилище Live не является целью установки.'),
('07-transferred.png','5. Перенос завершён','Образ скопирован и проверен побайтно. Раздел ext4 расширен, initramfs пересобран, загрузчик обновлён. Создан новый идентификатор проверки конечной системы.'),
('09-final-data.png','6. Загрузка конечного диска без Live','Во внешней VM подключён конечный qcow2. Live ISO, внутренней VM и рабочего диска больше нет. Корневой раздел — 39 ГиБ; файл, созданный в превью, сохранён; сессия — Wayland.'),
('10-final-second-boot.png','7. Повторная загрузка','Проверка подтверждает сохранность данных после второго запуска конечной системы. Все автоматические проверки пройдены, ручная проверка приложений подтверждена.')]
body='''<header><div class="label">AGIOS · ПОЛНЫЙ INSTALLATION FLOW · 17 СЕНТЯБРЯ 2026</div><h1>Hyprland: от превью до установленной системы.</h1><p>Реальный тест завершён: Live → сайт с агентом → Hyprland в превью → перенос на конечный диск → две загрузки без Live ISO. Все снимки встроены в HTML; запускать систему для просмотра не нужно.</p></header>
<div class="flow"><strong>Live + localhost</strong><span>→</span><strong>Hyprland / Guacamole</strong><span>→</span><strong>Подтверждение диска</strong><span>→</span><strong>Установленная система</strong></div>
<div class="grid"><section class="card"><h2>Что проверено</h2><ul><li>Конфигурацию подготовила реальная модель: Hyprland 0.56.2, Waybar, foot, wofi, Thunar и SDDM.</li><li>Новый внутренний диск 32 ГиБ установлен и загружен без установочного ISO.</li><li>Конечный виртуальный диск 40 ГиБ получил точную копию системы с настройками и пользовательским файлом.</li><li>Побайтная проверка, расширение ext4 до 39 ГиБ и установка загрузчика завершились.</li><li>Две загрузки конечного диска: вход, Wayland, сеть, пакеты и сохранность данных подтверждены.</li><li>28 тестов движка + 20 тестов веб-части; проверка JavaScript и shell-синтаксиса.</li></ul></section>
<section class="card"><h2>Границы результата</h2><ul><li>Конечная установка проверена на отдельном виртуальном диске внешней тестовой машины. На физическое железо система не устанавливалась.</li><li>Перенос пока поддерживает UEFI и ext4 с полной заменой содержимого выбранного диска.</li><li>Hyprland работает с virtio-vga и программным рендерингом Mesa. Вложенное 3D не прошло проверку; ускоренный режим оставлен экспериментальным.</li><li>Прототип собирается из локального кэша и существующего ISO; это не универсальный релиз для любого оборудования.</li><li>Во время теста исправлены ожидание разделов NBD и проверка ext4 перед расширением. Неудачные попытки не отмечались как успешные.</li><li>Сеть хоста не перенастраивалась. Скриншоты — внешние материалы QA, в продукте такой функции нет.</li></ul></section></div>'''
for name,title,caption in sections:
 data=base64.b64encode((root/name).read_bytes()).decode()
 body+=f'<section><h2>{html.escape(title)}</h2><p>{html.escape(caption)}</p><img src="data:image/png;base64,{data}" alt="{html.escape(title)}"></section>'
body+='<details class="card"><summary>Предыдущая проверка: Live + XFCE, до реализации переноса</summary>'+legacy+'</details>'
body+='<footer>Основной образ: out/agi-os-live-web.iso. Конечный тестовый диск: .local/live-test-final.qcow2. Исходные снимки и журнал переноса находятся в docs/test-results/2026-09-17-hyprland.</footer>'
(folder/'index.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AGIOS · Hyprland · полный flow</title><style>'+style+'summary{cursor:pointer;font-weight:600}details>header{margin-top:35px}</style><main>'+body+'</main></html>')
print(folder/'index.html')
