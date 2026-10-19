import { test } from "node:test";
import assert from "node:assert/strict";
import { homeTasteReady } from "../../web/js/features/home/taste-readiness.js";

test("onboarding favorites personalize Home before global confidence reaches 18%", () => {
  assert.equal(homeTasteReady({ interactions: 5, confidence: 0.0234,
    dimensions: { genres: { Thriller: 12.5 }, media_types: { movie: 6 } } }), true);
});
test("incidental behavior and media type alone do not unlock personalized Home", () => {
  assert.equal(homeTasteReady({ interactions: 2, confidence: 0.009,
    dimensions: { genres: { Action: 0.3 }, media_types: { movie: 4 } } }), false);
  assert.equal(homeTasteReady({ interactions: 0, confidence: 0.5,
    dimensions: { genres: { Action: 10 } } }), false);
});
test("mature profiles retain normal readiness without genre metadata", () => {
  assert.equal(homeTasteReady({ interactions: 52, confidence: 0.6, dimensions: {} }), true);
});
