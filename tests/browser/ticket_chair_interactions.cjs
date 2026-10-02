// Real ticket templates/assets; a disposable HTTP stub models Core's 204 response.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');

const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const root = process.cwd();
let source = 'unknown';
let failNextSave = false;
let pendingFlash = false;
let getCount = 0;
let postCount = 0;
let rentalEnabled = false;

const server = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://localhost');
  if (url.pathname === '/tickets/mine' && request.method === 'GET') {
    getCount += 1;
    response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'});
    const pages = rentalEnabled ? fixture.pages : fixture.pagesRentalOff;
    response.end(pages[source].replace('<!-- save-result -->', pendingFlash ? fixture.notification : ''));
    pendingFlash = false;
    return;
  }
  if (request.method === 'POST') {
    postCount += 1;
    const match = url.pathname.match(/^\/tickets\/tickets\/([^/]+)\/chair_source\/(user|venue|rental)$/);
    assert.ok(match, 'Choice must use the real Core URL');
    assert.equal(match[1], fixture.ticketIds[0]);
    if (failNextSave || (match[2] === 'rental' && !rentalEnabled)) {
      failNextSave = false;
      response.writeHead(403);
    } else {
      source = match[2];
      pendingFlash = true;
      response.writeHead(204);
    }
    response.end();
    return;
  }
  let relative;
  if (url.pathname.startsWith('/static/')) {
    relative = 'byceps/static/' + url.pathname.slice('/static/'.length);
  } else if (url.pathname.startsWith('/static_sites/totalverplant-36/')) {
    relative = 'sites/totalverplant-36/static/'
      + url.pathname.slice('/static_sites/totalverplant-36/'.length);
  }
  if (relative && fs.existsSync(path.join(root, relative))) {
    const contentType = relative.endsWith('.css') ? 'text/css'
      : relative.endsWith('.js') ? 'text/javascript' : 'image/svg+xml';
    response.writeHead(200, {'Content-Type': contentType});
    response.end(fs.readFileSync(path.join(root, relative)));
  } else {
    response.writeHead(404);
    response.end();
  }
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({headless: true});
  try {
    for (const theme of ['light', 'dark']) {
      for (const [width, enabled] of [[1280, false], [1280, true], [390, false], [390, true]]) {
        rentalEnabled = enabled;
        source = 'unknown';
        failNextSave = false;
        pendingFlash = false;
        getCount = 0;
        postCount = 0;
        const page = await browser.newPage({viewport: {width, height: 900}});
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.addInitScript(value => {
          document.addEventListener('DOMContentLoaded', () => {
            document.documentElement.dataset.theme = value;
          });
        }, theme);
        const target = origin + '/tickets/mine#ticket-' + fixture.ticketIds[0];
        await page.goto(target);
        await page.waitForLoadState('networkidle');
        const field = () => page.locator('#ticket-' + fixture.ticketIds[0] + ' .chair-information');
        assert.equal(await field().locator('.data-value').textContent(), fixture.labels.unknown);
        assert.equal(await field().locator('[data-action="set-chair-source"]').count(), enabled ? 3 : 2);
        assert.equal(await field().getAttribute('data-chair-source'), 'unknown');
        assert.equal(await field().locator('a[href$="/chair_source/unknown"]').count(), 0);

        // The last option must be clickable even over the next card/footer.
        for (const id of fixture.ticketIds) {
          const field = page.locator('#ticket-' + id + ' .chair-information');
          await field.locator('.dropdown-toggle').click();
          const lastChoice = field.locator('[data-action="set-chair-source"]').last();
          await lastChoice.scrollIntoViewIfNeeded();
          assert.equal(await lastChoice.evaluate(element => {
            const bounds = element.getBoundingClientRect();
            const hit = document.elementFromPoint(bounds.x + bounds.width / 2,
              bounds.y + bounds.height / 2);
            return element.contains(hit);
          }), true, `Menu is obscured at ${width}px in ${theme} theme`);
          const menuBounds = await field.locator('.dropdown-menu').boundingBox();
          assert.ok(menuBounds.x >= 0 && menuBounds.x + menuBounds.width <= width,
            'Menu must remain inside the horizontal viewport');
          await field.locator('.dropdown-toggle').click();
        }

        // The running app previously served old markup alongside the new asset.
        await field().locator('.chair-update-success').evaluate(element => element.remove());
        await field().locator('.dropdown-toggle').click();
        const getBeforeSave = getCount;
        const scrollBeforeSave = await page.evaluate(() => window.scrollY);
        await page.evaluate(() => { window.chairPageMarker = true; });
        await field().locator('a[href$="/chair_source/user"]').click();
        await field().locator('.chair-update-success').waitFor({state: 'visible'});
        assert.equal(getCount, getBeforeSave + 1, 'Saving must fetch the page to consume the flash');
        assert.equal(postCount, 1, 'A choice must be submitted exactly once');
        assert.equal(pendingFlash, false, 'The background GET must consume the queued flash');
        assert.equal(await page.locator('.bote-notices').count(), 0, 'The confirmation belongs at the ticket');
        assert.equal(page.url(), target, 'Save must preserve the URL');
        assert.equal(await page.evaluate(() => window.chairPageMarker), true, 'Save must not navigate');
        assert.equal(await page.evaluate(() => window.scrollY), scrollBeforeSave, 'Save must preserve the scroll position');
        assert.equal(await field().locator('.dropdown').evaluate(element => element.classList.contains('open')), false);
        assert.equal(await page.locator('#ticket-' + fixture.ticketIds[1] + ' .chair-update-success').isVisible(), false);
        assert.equal(await field().locator('.data-value').textContent(), fixture.labels.user);
        assert.ok((await field().locator('.chair-update-success').textContent()).includes('FIXTURE-1'));

        // A failed save must keep the current answer and permit a retry.
        // Reproduce a page rendered by an older container without a status slot.
        await field().locator('.chair-update-success').evaluate(element => element.remove());
        await field().locator('.dropdown-toggle').click();
        failNextSave = true;
        const getBeforeFailure = getCount;
        const scrollBeforeFailure = await page.evaluate(() => window.scrollY);
        await field().locator('a[href$="/chair_source/venue"]').click();
        await field().locator('.chair-update-error').waitFor({state: 'visible'});
        assert.equal(getCount, getBeforeFailure);
        assert.equal(await field().locator('.data-value').textContent(), fixture.labels.user);
        assert.equal(await field().locator('.dropdown-toggle').isEnabled(), true);
        assert.equal(await field().locator('.chair-update-success').isVisible(), false);
        assert.equal(await page.evaluate(() => window.scrollY), scrollBeforeFailure);

        await field().locator('a[href$="/chair_source/venue"]').click();
        await field().locator('.chair-update-success').waitFor({state: 'visible'});
        assert.equal(await field().locator('.data-value').textContent(), fixture.labels.venue);
        assert.equal(page.url(), target);
        assert.equal(await page.evaluate(() => window.scrollY), scrollBeforeFailure);
        assert.equal(postCount, 3);
        await field().locator('.dropdown-toggle').click();
        await field().locator('a[href$="/chair_source/user"]').click();
        await field().locator('.chair-update-success').waitFor({state: 'visible'});
        assert.equal(await field().locator('.data-value').textContent(), fixture.labels.user);
        assert.equal(postCount, 4, 'The menu must remain usable after both choices');
        await page.reload();
        assert.equal(await field().locator('.data-value').textContent(), fixture.labels.user, 'The saved choice must survive a reload');
        assert.equal(await page.locator('.bote-notices').count(), 0, 'The consumed flash must not reappear after reload');
        await field().locator('.dropdown-toggle').click();
        assert.equal(await field().locator('.dropdown-menu').isVisible(), true, 'The menu must still open after reload');
        if (enabled) {
          await field().locator('a[href$="/chair_source/rental"]').click();
          await field().locator('.chair-update-success').waitFor({state: 'visible'});
          assert.equal(await field().locator('.data-value').textContent(), fixture.labels.rental);
          assert.equal(await field().getAttribute('data-chair-source'), 'rental');
          const postsBeforeDuplicate = postCount;
          await field().locator('.dropdown-toggle').click();
          await field().locator('a[href$="/chair_source/rental"]').click();
          assert.equal(postCount, postsBeforeDuplicate, 'Repeated rental selection must not write again');
          rentalEnabled = false;
          await page.reload();
          assert.equal(await field().locator('.data-value').textContent(), fixture.labels.rental);
          assert.equal(await field().locator('a[href$="/chair_source/rental"]').count(), 0);
        }
        assert.deepEqual(errors, []);
        await page.close();
      }
    }
    console.log('PASS: rental OFF/ON and retained rental answers, unknown DOM state, legacy markup compatibility, repeated chair choices, dropdown layering, light/dark desktop/mobile, inline confirmation without navigation, failed-save retry and persistence after reload');
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
