import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import zlib from 'node:zlib';

const root = path.resolve('dist');
const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
  entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.join(dir, entry.name)]);
assert(fs.existsSync(root), 'dist is missing; run the site build first');
const files = walk(root);
const htmlFiles = files.filter((file) => file.endsWith('.html'));
const indexableFiles = htmlFiles.filter((file) => !file.endsWith(`${path.sep}404.html`));
const titles = new Set();
const descriptions = new Set();
let internalReferences = 0;

for (const file of htmlFiles) {
  const html = fs.readFileSync(file, 'utf8');
  const is404 = file.endsWith(`${path.sep}404.html`);
  const route = `/${path.relative(root, file).replaceAll('\\', '/').replace(/index\.html$/, '')}`;
  assert.match(html, /<h1[^>]*>.+?<\/h1>/s, `missing h1: ${route}`);
  const title = html.match(/<title>(.*?)<\/title>/s)?.[1];
  const description = html.match(/name="description" content="(.*?)"/s)?.[1];
  assert(title, `missing title: ${route}`);
  assert(description, `missing description: ${route}`);
  assert(!titles.has(title), `duplicate title: ${title}`);
  assert(!descriptions.has(description), `duplicate description: ${route}`);
  titles.add(title);
  descriptions.add(description);
  assert.equal((html.match(/rel="canonical"/g) || []).length, 1, `canonical count: ${route}`);
  assert.match(html, /<html lang="(?:en|ja)"/);
  assert.match(html, /id="main"/);
  if (!is404) {
    assert(!html.includes('noindex'), `indexable page contains noindex: ${route}`);
    assert(html.includes(`href="https://kabuforge.com${route}"`), `canonical URL mismatch: ${route}`);
    const alternates = [...html.matchAll(/rel="alternate" hreflang="(.*?)" href="(.*?)"/g)];
    assert.equal(alternates.length, 3, `alternate count: ${route}`);
    for (const [, language, url] of alternates) {
      const alternateRoute = new URL(url).pathname;
      const target = path.join(root, alternateRoute, 'index.html');
      assert(fs.existsSync(target), `missing alternate page: ${url}`);
      if (language !== 'x-default') {
        const alternateHtml = fs.readFileSync(target, 'utf8');
        assert(alternateHtml.includes(`href="https://kabuforge.com${route}"`), `nonreciprocal alternate: ${url}`);
      }
    }
  } else {
    assert(html.includes('noindex'), '404 page should be noindex');
  }
  for (const [, source] of html.matchAll(/(?:href|src)="([^"#]+)"/g)) {
    if (source.startsWith('/')) {
      const clean = source.split('#')[0];
      assert(fs.existsSync(path.join(root, clean)) || fs.existsSync(path.join(root, clean, 'index.html')), `broken link ${source} in ${route}`);
      internalReferences++;
    }
  }
  for (const [, img] of html.matchAll(/(<img\b[^>]*>)/g)) {
    assert.match(img, /alt=/, `image missing alt: ${route}`);
    assert.match(img, /width=/, `image missing width: ${route}`);
    assert.match(img, /height=/, `image missing height: ${route}`);
  }
  for (const [, json] of html.matchAll(/<script type="application\/ld\+json">(.*?)<\/script>/gs)) JSON.parse(json);
}

const sitemap = fs.readFileSync(path.join(root, 'sitemap.xml'), 'utf8');
const sitemapUrls = [...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map((match) => match[1]);
assert.equal(sitemapUrls.length, indexableFiles.length, 'sitemap count must match built indexable pages');
assert.equal(new Set(sitemapUrls).size, sitemapUrls.length, 'sitemap URLs must be unique');
for (const url of sitemapUrls) assert(fs.existsSync(path.join(root, new URL(url).pathname, 'index.html')), `sitemap target missing: ${url}`);
assert.match(fs.readFileSync(path.join(root, 'robots.txt'), 'utf8'), /Allow: \/[\s\S]*Sitemap: https:\/\/kabuforge\.com\/sitemap\.xml/);

const layout = fs.readFileSync('src/layouts/Layout.astro', 'utf8');
const version = layout.match(/version:'([^']+)'/)?.[1];
assert(version, 'homepage software schema must declare a version');
const packageVersion = version.replace(/^v/, '');
const license = layout.match(/license:'https:\/\/spdx\.org\/licenses\/([^']+?)\.html'/)?.[1];
assert(license, 'homepage software schema must declare an SPDX license');
const pages = JSON.parse(fs.readFileSync('src/data/pages.json', 'utf8'));
const releasePage = pages.find((page) => page.slug === 'releases');
const releaseText = JSON.stringify(releasePage?.sections?.[0] ?? {});
assert(releasePage, 'release page missing');
assert(releaseText.includes(`v${packageVersion}`) && releaseText.includes(license), 'release page does not match current schema version/license');
assert(releaseText.includes(`releases/tag/v${packageVersion}`), 'release page must link to current stable tag');
const englishDocs = pages.find((page) => page.slug === 'docs');
const japaneseDocs = pages.find((page) => page.slug === 'ja/docs');
const englishQuickstart = pages.find((page) => page.slug === 'docs/quickstart');
const japaneseQuickstart = pages.find((page) => page.slug === 'ja/docs/quickstart');
for (const [docs, quickstart] of [[englishDocs, englishQuickstart], [japaneseDocs, japaneseQuickstart]]) {
  assert(docs, 'localized docs overview missing');
  assert(quickstart, 'localized quickstart missing');
  const text = JSON.stringify(docs);
  assert(text.includes(`v${packageVersion}`) && text.includes(packageVersion), `docs overview does not identify current release: ${docs.slug}`);
  assert(text.includes('does not submit real orders') || text.includes('実注文'), `docs overview must state the order boundary: ${docs.slug}`);
  assert(text.includes('PIT') || text.includes('available_at'), `docs overview must identify PIT scope: ${docs.slug}`);
  const quickstartText = JSON.stringify(quickstart);
  assert(quickstartText.includes(`v${packageVersion}`) && quickstartText.includes(packageVersion), `quickstart does not pin the current package/tag: ${quickstart.slug}`);
  assert(quickstartText.includes(`git checkout v${packageVersion}`), `quickstart source example must checkout current tag: ${quickstart.slug}`);
}
for (const homepagePath of ['index.html', 'ja/index.html']) {
  const home = fs.readFileSync(path.join(root, homepagePath), 'utf8');
  assert(home.includes(`>${packageVersion} · tag v${packageVersion} · Python 3.12+ · ${license}<`), `homepage release header mismatch: ${homepagePath}`);
  const graph = [...home.matchAll(/<script type="application\/ld\+json">(.*?)<\/script>/gs)].map((match) => JSON.parse(match[1]));
  const software = graph.flatMap((item) => item['@graph'] ?? [item]).find((item) => item['@type'] === 'SoftwareSourceCode');
  assert(software, `homepage SoftwareSourceCode JSON-LD missing: ${homepagePath}`);
  assert.equal(software.name, 'KabuForge');
  assert.equal(software.url, 'https://kabuforge.com/');
  assert.equal(software.codeRepository, 'https://github.com/Siyuan-chat/KabuForge');
  assert.equal(software.license, `https://spdx.org/licenses/${license}.html`);
  assert.equal(software.version, packageVersion);
  assert.equal(software.programmingLanguage, 'Python');
  assert(software.description, `SoftwareSourceCode JSON-LD needs a factual description: ${homepagePath}`);
}
const llms = fs.readFileSync('public/llms.txt', 'utf8');
assert(llms.includes(`v${packageVersion}`) && llms.includes(license), 'llms.txt current release/license mismatch');
assert(llms.includes(`https://github.com/Siyuan-chat/KabuForge/releases/tag/v${packageVersion}`), 'llms.txt current release link missing');

const inlineBytes = htmlFiles.reduce((total, file) => total + [...fs.readFileSync(file, 'utf8').matchAll(/<script(?![^>]*application\/ld\+json)[^>]*>(.*?)<\/script>/gs)].reduce((size, match) => size + zlib.gzipSync(match[1]).length, 0), 0);
const jsBytes = inlineBytes + files.filter((file) => file.endsWith('.js')).reduce((total, file) => total + zlib.gzipSync(fs.readFileSync(file)).length, 0);
assert(jsBytes < 100 * 1024, 'gzip JavaScript budget exceeded');
console.log(JSON.stringify({ passed: true, htmlPages: htmlFiles.length, indexablePages: indexableFiles.length, internalReferences, gzipJavaScriptBytes: jsBytes, currentVersion: packageVersion, license, checks: ['unique metadata', 'canonical', 'reciprocal hreflang', 'internal links/assets', 'image dimensions and alt', 'JSON-LD parse and current software facts', 'docs/release/llms consistency', 'dynamic sitemap count', 'robots', 'JS budget'] }));
