import { expect, test, type Page } from "@playwright/test";

// The backend runs with the fake provider: it replies "(fake reply) You said: <message>".
// Markers such as [fake:fail_once] or [fake:slow] in a message simulate provider behaviour.

const shots = (name: string) => `e2e/screenshots/${name}.png`;
const uniqueEmail = (tag: string) => `${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;

async function register(page: Page, email = uniqueEmail("user")) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "How can we help?" })).toBeVisible();
  return email;
}

async function sendMessage(page: Page, text: string) {
  // The composer ignores sends while a reply is generating; wait for the previous one to finish.
  await expect(page.getByRole("button", { name: "Stop" })).toBeHidden();
  const input = page.getByLabel("Message");
  await input.fill(text);
  await input.press("Enter");
}

const assistantMessages = (page: Page) => page.getByTestId("assistant-message");

/** Wait until the latest reply has finished (fake replies always start with this prefix). */
async function waitForReply(page: Page, count: number) {
  await expect(assistantMessages(page)).toHaveCount(count);
  await expect(assistantMessages(page).last()).toContainText("(fake reply)");
  await expect(page.getByRole("button", { name: "Stop" })).toBeHidden();
}

test("register, chat with a streamed reply, and history persists after reload", async ({ page }) => {
  await register(page);
  await page.screenshot({ path: shots("01-empty-chat") });

  await sendMessage(page, "Where is my order #42?");
  await expect(page).toHaveURL(/\/c\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("user-message")).toHaveText("Where is my order #42?");
  await expect(assistantMessages(page).last()).toContainText("(fake reply) You said: Where is my order #42?");

  // Auto-title appears in the header and the sidebar.
  await expect(page.getByTestId("conversation-title")).toHaveText("Where is my order #42?");
  await expect(page.getByTestId("conversation-list")).toContainText("Where is my order #42?");

  await sendMessage(page, "And when will it arrive?");
  await expect(assistantMessages(page)).toHaveCount(2);
  await expect(assistantMessages(page).last()).toContainText("And when will it arrive?");
  await page.screenshot({ path: shots("02-conversation") });

  await page.reload();
  await expect(page.getByTestId("user-message")).toHaveCount(2);
  await expect(assistantMessages(page)).toHaveCount(2);
  await expect(assistantMessages(page).first()).toContainText("Where is my order #42?");
});

test("conversations stay separate and can be renamed and deleted", async ({ page }) => {
  await register(page);
  await sendMessage(page, "First topic");
  await waitForReply(page, 1);
  const firstUrl = page.url();

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "How can we help?" })).toBeVisible();
  await sendMessage(page, "Second topic");
  await waitForReply(page, 1);
  await expect(page.getByTestId("user-message")).toHaveText("Second topic");

  const list = page.getByTestId("conversation-list");
  await expect(list.getByRole("link")).toHaveCount(2);
  await list.getByRole("link", { name: "First topic" }).click();
  await expect(page).toHaveURL(firstUrl);
  await expect(page.getByTestId("user-message")).toHaveText("First topic");

  // Rename
  await list.getByRole("link", { name: "First topic" }).hover();
  await page.getByRole("button", { name: "Rename First topic" }).click();
  await page.getByLabel("Conversation title").fill("Billing question");
  await page.getByLabel("Conversation title").press("Enter");
  await expect(list).toContainText("Billing question");
  await expect(page.getByTestId("conversation-title")).toHaveText("Billing question");

  // Delete the open conversation -> back to a new chat
  page.once("dialog", (d) => d.accept());
  await list.getByRole("link", { name: "Billing question" }).hover();
  await page.getByRole("button", { name: "Delete Billing question" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(list.getByRole("link")).toHaveCount(1);
});

test("a failed reply shows an error and Retry regenerates it", async ({ page }) => {
  await register(page);
  await sendMessage(page, "What are your opening hours? [fake:fail_once]");

  const error = page.getByTestId("message-error");
  await expect(error).toContainText("temporarily unavailable");
  await page.screenshot({ path: shots("03-failed-reply") });

  await page.getByRole("button", { name: "Retry" }).click();
  await expect(assistantMessages(page).last()).toContainText("(fake reply) You said: What are your opening hours?");
  await expect(error).toHaveCount(0);
  await expect(assistantMessages(page)).toHaveCount(1); // regenerated in place, no duplicate

  await page.reload();
  await expect(assistantMessages(page)).toHaveCount(1);
  await expect(assistantMessages(page).last()).toContainText("You said: What are your opening hours?");
});

test("Stop cancels a streaming reply; partial text is kept and can be retried", async ({ page }) => {
  await register(page);
  await sendMessage(page, "one two three four five six seven eight nine ten [fake:slow]");

  const stop = page.getByRole("button", { name: "Stop" });
  await expect(stop).toBeVisible();
  await expect(assistantMessages(page).last()).toContainText("(fake reply)");
  await stop.click();

  await expect(page.getByTestId("message-error")).toContainText("stopped");
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  const partial = await assistantMessages(page).last().innerText();
  expect(partial).not.toContain("ten");
  await page.screenshot({ path: shots("04-stopped") });

  // The server recorded the cancellation (survives reload) and offers Retry.
  await page.reload();
  await expect(page.getByTestId("message-error")).toContainText("stopped");
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
});

test("validation and rejected sends are explained to the user", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(uniqueEmail("v"));
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("alert")).toContainText("at least 8 characters");

  await register(page);
  await sendMessage(page, "hello");
  await waitForReply(page, 1);
  await sendMessage(page, "x".repeat(8001));
  await expect(page.getByTestId("send-notice")).toContainText("limited to 8000 characters");
  await expect(page.getByTestId("user-message")).toHaveCount(1); // the rejected message was not added
});

test("users cannot see each other's conversations", async ({ browser }) => {
  const alice = await browser.newPage();
  await register(alice, uniqueEmail("alice"));
  await sendMessage(alice, "Alice private question");
  await expect(alice.getByTestId("assistant-message")).toHaveCount(1);
  const aliceUrl = alice.url();

  const bobContext = await browser.newContext();
  const bob = await bobContext.newPage();
  await register(bob, uniqueEmail("bob"));
  await expect(bob.getByTestId("conversation-list").getByRole("link")).toHaveCount(0);
  await bob.goto(aliceUrl);
  await expect(bob.getByText("This conversation could not be loaded")).toBeVisible();
  await expect(bob.getByText("Alice private question")).toHaveCount(0);
  await bobContext.close();
});

test("sign out and sign back in", async ({ page }) => {
  const email = await register(page);
  await sendMessage(page, "remember this");
  await waitForReply(page, 1);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/); // protected route

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Incorrect email or password");

  await page.getByLabel("Password").fill("e2e-password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("conversation-list")).toContainText("remember this");
});

test("mobile layout: sidebar is a drawer", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await register(page);
  await sendMessage(page, "Hello from my phone");
  await expect(page.getByTestId("assistant-message")).toHaveCount(1);
  await page.screenshot({ path: shots("05-mobile-chat") });

  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("button", { name: "New chat" })).toBeVisible();
  await page.screenshot({ path: shots("06-mobile-drawer") });
  await page.getByRole("link", { name: "Hello from my phone" }).click();
  await expect(page.getByRole("button", { name: "New chat" })).toBeHidden();
  await context.close();
});

test("navigating away mid-reply does not lose it; coming back shows the finished reply", async ({ page }) => {
  await register(page);
  await sendMessage(page, "alpha beta gamma delta [fake:slow]");
  await expect(page.getByRole("button", { name: "Stop" })).toBeVisible();
  const url = page.url();

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page.getByRole("heading", { name: "How can we help?" })).toBeVisible();

  // In-app navigation (a full reload or closed tab ends the request, and the server records a cancel).
  await page.getByTestId("conversation-list").getByRole("link").first().click();
  await expect(page).toHaveURL(url);
  await expect(page.getByTestId("user-message")).toHaveText("alpha beta gamma delta [fake:slow]");
  await expect(assistantMessages(page).last()).toContainText("You said: alpha beta gamma delta", {
    timeout: 15_000,
  });
  await expect(page.getByTestId("message-error")).toHaveCount(0);
});

test("a reply cut off by the length limit is flagged", async ({ page }) => {
  await register(page);
  await sendMessage(page, "tell me everything [fake:length]");
  await expect(page.getByTestId("message-note")).toContainText("maximum length");
  await page.reload();
  await expect(page.getByTestId("message-note")).toContainText("maximum length");
});
