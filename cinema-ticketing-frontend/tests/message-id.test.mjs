import test from "node:test";
import assert from "node:assert/strict";
import { createMessageId } from "../src/chat/messageId.ts";

test("uses a local fallback when randomUUID is unavailable on HTTP", () => {
  const id = createMessageId(null);

  assert.match(id, /^message-[a-z0-9]+-[a-z0-9]+$/);
});

test("uses the secure-context UUID API when it is available", () => {
  assert.equal(createMessageId(() => "browser-uuid"), "browser-uuid");
});
