// Сообщает поисковикам с IndexNow (Bing, Яндекс, Seznam, Naver) об адресах сайта.
// Запускать после деплоя: `npm run indexnow`. Список берётся из живого sitemap.xml, поэтому он
// всегда совпадает с тем, что задеплоено. Ключ — файл `public/<ключ>.txt`, который сайт отдаёт
// с корня: по нему поисковик проверяет, что запрос пришёл от владельца домена.
import { readdirSync } from 'node:fs'

const site = process.env.SITE_URL ?? 'https://agios.complexity.solutions'
const publicDir = new URL('../public/', import.meta.url)

const keyFile = readdirSync(publicDir).find((name) => /^[0-9a-f]{32}\.txt$/.test(name))
if (!keyFile) throw new Error('IndexNow key file public/<key>.txt not found')
const key = keyFile.slice(0, -'.txt'.length)

const sitemap = await fetch(`${site}/sitemap.xml`)
if (!sitemap.ok) throw new Error(`sitemap.xml: HTTP ${sitemap.status}`)
const urlList = [...(await sitemap.text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1])

const response = await fetch('https://api.indexnow.org/indexnow', {
  method: 'POST',
  headers: { 'content-type': 'application/json; charset=utf-8' },
  body: JSON.stringify({ host: new URL(site).host, key, keyLocation: `${site}/${keyFile}`, urlList }),
})

// 200 — принято, 202 — принято, ключ ещё проверяется; остальное — ошибка.
console.log(`IndexNow: HTTP ${response.status} for ${urlList.length} URLs`)
if (response.status !== 200 && response.status !== 202) {
  console.error(await response.text())
  process.exit(1)
}
