import { readFile } from 'node:fs/promises'

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const indexHtml = await readFile(new URL('../index.html', import.meta.url), 'utf8')
const faviconSvg = await readFile(new URL('../public/favicon.svg', import.meta.url), 'utf8')

assert(
  indexHtml.includes('<link rel="icon" type="image/svg+xml" href="/favicon.svg" />'),
  'index.html references the SVG favicon'
)
assert(faviconSvg.includes('viewBox="0 0 32 32"'), 'favicon uses a 32x32 SVG viewBox')
assert(faviconSvg.includes('>Q<'), 'favicon shows the Q lettermark')
