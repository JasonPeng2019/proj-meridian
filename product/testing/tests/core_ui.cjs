// One remote browser, built App.tsx, actual loopback FastAPI; no API interception.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { createRequire } = require("node:module");

async function run() {
  assert.equal(process.env.GITHUB_ACTIONS, "true", "Remote Actions only");
  assert.equal(process.env.GITHUB_REF, "refs/heads/harness-v2");
  const [base, casePath, output] = process.argv.slice(2);
  const origin = new URL(base);
  assert.equal(origin.hostname, "127.0.0.1");
  assert.equal(origin.protocol, "http:");
  const source = JSON.parse(fs.readFileSync(casePath, "utf8"));
  assert.equal(source.commit, process.env.GITHUB_SHA);
  assert.equal(source.fact.display.state, "value");
  assert.equal(source.fact.fixture, false);
  assert.equal(source.fact.synthetic, false);
  const root = path.resolve(__dirname, "../..");
  const browserRequire = createRequire(path.join(root, "development/.runtime/ci-browser/package.json"));
  const { chromium } = browserRequire("playwright");
  const errors = [], requests = [], imageHashes = [];
  const report = { commit: source.commit, outcome: "FAIL", scope: "Real built Chat/Parts/PartPage and FastAPI; Responses scripted from source tool values", checks: [] };
  let browser, context, page;
  const checked = name => report.checks.push({ name, outcome: "PASS" });
  const partPath = `/api/parts/${source.part_id}`;
  const isPart = (response, suffix = "") => response.request().method() === "GET"
    && decodeURIComponent(new URL(response.url()).pathname) === partPath + suffix;
  const isConversation = (response, id, method = "GET", suffix = "") => response.request().method() === method
    && new URL(response.url()).pathname === `/api/conversations/${id}${suffix}`;
  async function loadedImage(responsePromise) {
    const response = await responsePromise;
    assert.equal(response.status(), 200);
    assert.match(response.headers()["content-type"], /^image\/png/);
    assert.equal(response.headers()["x-meridian-fixture"], undefined);
    await page.waitForFunction(() => {
      const image = document.querySelector(".mp-paper img");
      return image?.complete && image.naturalWidth > 0;
    });
    // Read the actual Blob displayed by PartPage. Chromium's protocol buffer
    // returned empty for this consumed fetch in run 42045204199, even though
    // all 155219 bytes arrived and the screenshot showed the decoded drawing.
    const bytes = Buffer.from(await page.locator(".mp-paper img").evaluate(async image =>
      Array.from(new Uint8Array(await (await fetch(image.currentSrc)).arrayBuffer()))));
    assert.equal(bytes.subarray(0, 8).toString("hex"), "89504e470d0a1a0a");
    assert.equal(bytes.length, Number(response.headers()["content-length"]));
    const hash = createHash("sha256").update(bytes).digest("hex");
    assert.equal(hash, source.image_sha256);
    imageHashes.push(hash);
    const dimensions = await page.locator(".mp-paper img").evaluate(image => [image.naturalWidth, image.naturalHeight]);
    assert.deepEqual(dimensions, [source.geometry.image_width, source.geometry.image_height]);
  }
  async function selectedChat(id) {
    await page.waitForFunction(id => new URL(location.href).searchParams.get("conversation") === id, id);
    await page.locator('.mc-messages[aria-busy="false"]').waitFor();
  }
  async function restoredAnswer() {
    const answer = page.getByRole("article", { name: "Meridian answer", exact: true });
    await answer.waitFor();
    assert.ok((await page.getByRole("article", { name: "Your message", exact: true }).innerText()).includes(source.question));
    assert.ok((await answer.innerText()).includes(source.answer_prefix));
    assert.ok(!(await answer.innerText()).includes("[cite:"));
    await answer.getByRole("button", { name: /^Sources/ }).first().waitFor();
    await answer.getByRole("button", { name: "Drawing", exact: true }).waitFor();
    return answer;
  }
  try {
    browser = await chromium.launch({ headless: true, args: ["--renderer-process-limit=1", "--num-raster-threads=1", "--disable-background-networking"] });
    context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: "block" });
    await context.tracing.start({ screenshots: true, snapshots: true });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      const url = new URL(response.url());
      if (url.origin === origin.origin && (url.pathname.startsWith("/api/") || url.pathname.startsWith("/assets/"))) {
        requests.push({ method: response.request().method(), path: url.pathname + url.search, status: response.status() });
        if (response.status() >= 400) errors.push(`${response.status()} ${url.pathname}`);
      }
    });
    await page.goto(base, { waitUntil: "networkidle" });
    await page.getByRole("heading", { level: 1, name: "Chat", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Debug", exact: true }).count(), 0);
    assert.ok(requests.some(request => request.path.startsWith("/assets/")), "The compiled frontend assets were not loaded");
    checked("built frontend and real status route");

    const navigation = page.getByRole("navigation", { name: "Main navigation" });
    await navigation.getByRole("button", { name: "Parts", exact: true }).click();
    const parts = page.locator(".meridian-parts");
    await parts.getByLabel("Find a part", { exact: true }).fill(source.part_id);
    const searched = page.waitForResponse(response => new URL(response.url()).pathname === "/api/parts"
      && new URL(response.url()).searchParams.get("q") === source.part_id);
    await parts.getByRole("button", { name: "Search", exact: true }).click();
    const summaries = await (await searched).json();
    assert.equal(summaries.length, 1);
    assert.equal(summaries[0].id, source.part_id);
    assert.equal(summaries[0].fixture, false);
    assert.equal(summaries[0].synthetic, false);
    const row = parts.locator(".ml-part").filter({ has: page.getByText(source.part_id, { exact: true }) });
    const detailed = page.waitForResponse(response => isPart(response));
    await row.getByRole("button", { name: "Open part", exact: true }).click();
    const detail = await (await detailed).json();
    assert.deepEqual(detail.facts[source.fact.fact], source.fact);
    const panel = page.getByRole("complementary", { name: "Selected part", exact: true });
    await panel.getByRole("heading", { name: source.display_name, exact: true }).waitFor();
    const inventoryImage = page.waitForResponse(response => isPart(response, "/image"));
    await panel.getByRole("tab", { name: "Drawing", exact: true }).click();
    await loadedImage(inventoryImage);
    checked("Parts search -> PartPage -> source PNG bytes and decoded image");
    await page.getByRole("button", { name: "Close part panel", exact: true }).click();
    await navigation.getByRole("button", { name: "Chat", exact: true }).click();

    const created = page.waitForResponse(response => new URL(response.url()).pathname === "/api/conversations"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    const id = (await (await created).json()).conversation.conversation_id;
    report.conversation_id = id;
    await selectedChat(id);
    await page.getByLabel("Your question", { exact: true }).fill(source.question);
    const sent = page.waitForResponse(response => isConversation(response, id, "POST", "/messages"));
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const sentResponse = await sent;
    assert.deepEqual(sentResponse.request().postDataJSON(), { message: source.question });
    assert.equal(sentResponse.status(), 200);
    const saved = await sentResponse.json();
    assert.equal(saved.messages.length, 2);
    const reply = saved.messages[1].response;
    assert.equal(reply.fixture, false);
    assert.equal(reply.synthetic, false);
    assert.deepEqual(reply.facts, { [source.fact.fact]: source.fact });
    assert.deepEqual(reply.warnings, []);
    assert.equal(reply.markers[0].valid, true);
    assert.deepEqual(reply.markers[0].names, [source.fact.fact]);
    assert.equal(reply.parts_to_show[0].id, source.part_id);
    assert.equal(reply.parts_to_show[0].reason, "citation");
    assert.ok(reply.parts_to_show[0].highlights.some(target => JSON.stringify(target) === JSON.stringify(source.fact.sources[source.drawing_source_index].target)));
    let answer = await restoredAnswer();
    checked("part question -> real tool-derived answer, valid citation and drawing attachment");

    await answer.getByRole("button", { name: /^Sources/ }).first().click();
    const popup = answer.getByRole("group", { name: "Citation sources", exact: true });
    const citedImage = page.waitForResponse(response => isPart(response, "/image"));
    await popup.locator(".me-source-row button").nth(source.drawing_source_index).click();
    await loadedImage(citedImage);
    await panel.locator(".mp-highlight").first().waitFor({ state: "visible" });
    const target = source.fact.sources[source.drawing_source_index].target;
    const highlight = await panel.locator(".mp-highlight").first().evaluate(element =>
      [element.style.left, element.style.top, element.style.width, element.style.height].map(parseFloat));
    const expected = target.box.map((value, index) => 100 * value / (index % 2 ? source.geometry.source_height : source.geometry.source_width));
    highlight.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 0.01));
    await page.screenshot({ path: path.join(output, "core-citation.png"), fullPage: true });
    checked("citation click -> actual drawing with source-coordinate highlight");
    await page.getByRole("button", { name: "Close part panel", exact: true }).click();

    const attachedImage = page.waitForResponse(response => isPart(response, "/image"));
    await answer.getByRole("button", { name: "Drawing", exact: true }).click();
    await loadedImage(attachedImage);
    const paper = panel.locator(".mp-paper");
    const before = (await paper.boundingBox()).width;
    await panel.getByRole("button", { name: "Zoom in", exact: true }).click();
    assert.equal(await panel.locator(".mp-zoom output").innerText(), "125%");
    assert.ok((await paper.boundingBox()).width > before * 1.24);
    await page.screenshot({ path: path.join(output, "core-drawing-zoom.png"), fullPage: true });
    await panel.getByRole("button", { name: "Zoom out", exact: true }).click();
    assert.equal(await panel.locator(".mp-zoom output").innerText(), "100%");
    await panel.getByRole("button", { name: "Zoom in", exact: true }).click();
    await panel.getByRole("button", { name: "Fit", exact: true }).click();
    assert.equal(await paper.evaluate(element => element.style.width), "100%");
    checked("attachment click -> decoded source drawing; zoom in/out and Fit change actual image size");
    await page.getByRole("button", { name: "Close part panel", exact: true }).click();

    const another = page.waitForResponse(response => new URL(response.url()).pathname === "/api/conversations"
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    const otherId = (await (await another).json()).conversation.conversation_id;
    assert.notEqual(otherId, id);
    await selectedChat(otherId);
    assert.equal(await page.getByRole("article", { name: "Meridian answer", exact: true }).count(), 0);
    await page.reload({ waitUntil: "networkidle" });
    await selectedChat(otherId);
    const readPast = page.waitForResponse(response => isConversation(response, id));
    await page.getByRole("complementary", { name: "Past chats", exact: true }).locator("li button")
      .filter({ has: page.getByText(saved.conversation.title, { exact: true }) }).click();
    const past = await (await readPast).json();
    assert.deepEqual(past.messages, saved.messages);
    assert.equal(past.ledger, undefined);
    await selectedChat(id);
    await restoredAnswer();
    const reloaded = page.waitForResponse(response => isConversation(response, id));
    await page.reload({ waitUntil: "networkidle" });
    assert.deepEqual((await (await reloaded).json()).messages, saved.messages);
    await selectedChat(id);
    answer = await restoredAnswer();
    const restoredImage = page.waitForResponse(response => isPart(response, "/image"));
    await answer.getByRole("button", { name: "Drawing", exact: true }).click();
    await loadedImage(restoredImage);
    await page.screenshot({ path: path.join(output, "core-past-chat.png"), fullPage: true });
    checked("new thread isolation, past-chat selection and full reload preserve answer/citation/attachment through real history routes");
    assert.deepEqual(errors, []);
    report.outcome = "PASS";
    console.log("PASS: actual corpus -> scripted Responses tools -> built UI citations/drawing/zoom -> persistent past chat");
  } catch (error) {
    report.error = error.stack || String(error);
    if (page) await page.screenshot({ path: path.join(output, "core-failure.png"), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    report.requests = requests;
    report.image_sha256 = imageHashes;
    report.browser_errors = errors;
    report.completed_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, "browser.json"), JSON.stringify(report, null, 2) + "\n");
    if (context) await context.tracing.stop({ path: path.join(output, "core-trace.zip") }).catch(() => {});
    if (browser) await browser.close();
  }
}

run().catch(error => { console.error(error); process.exitCode = 1; });
