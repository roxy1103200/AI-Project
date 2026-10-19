import test from "node:test";
import assert from "node:assert/strict";
import { OrderPosterResolver } from "../src/orders/order-posters.ts";

test("past orders resolve movies from the exact historical screening, independent of sale lists", async () => {
  const calls = [];
  const resolver = new OrderPosterResolver();
  const orders = [{ order_no: "old-a", screening_id: 1 }, { order_no: "old-b", screening_id: 1 }, { order_no: "new", screening_id: 56, movie_id: 13 }];
  const request = async path => { calls.push(path); return { id: 1, movie_id: 12 }; };
  const enriched = await resolver.resolve(orders, request);
  assert.deepEqual(enriched.map(order => order.movie_id), [12, 12, 13]);
  assert.deepEqual(calls, ["/api/screenings/1"]);
  assert.equal(orders[0].movie_id, undefined);
  await resolver.resolve(orders, request);
  assert.equal(calls.length, 1);
});

test("new responses need no compatibility lookups", async () => {
  const resolver = new OrderPosterResolver();
  const orders = [{ screening_id: 56, movie_id: 13 }];
  const result = await resolver.resolve(orders, async () => { assert.fail("Unexpected lookup"); });
  assert.equal(result[0], orders[0]);
});

test("missing or failed screening does not hide orders and can be retried on refresh", async () => {
  const resolver = new OrderPosterResolver();
  const orders = [{ screening_id: 4, order_no: "kept" }];
  const first = await resolver.resolve(orders, async () => { throw new Error("offline"); });
  assert.deepEqual(first, orders);
  const second = await resolver.resolve(orders, async () => ({ id: 4, movie_id: 13 }));
  assert.equal(second[0].movie_id, 13);
});

test("incorrect screening identities and malformed IDs never select another film", async () => {
  const resolver = new OrderPosterResolver();
  const orders = [{ screening_id: 4 }, { screening_id: -1 }, { screening_id: NaN }];
  const calls = [];
  const result = await resolver.resolve(orders, async path => { calls.push(path); return { id: 99, movie_id: 13 }; });
  assert.ok(result.every(order => order.movie_id === undefined));
  assert.deepEqual(calls, ["/api/screenings/4"]);
});

test("legacy lookup concurrency is bounded even for a long order history", async () => {
  const resolver = new OrderPosterResolver();
  const orders = Array.from({ length: 15 }, (_, index) => ({ screening_id: index + 1 }));
  let active = 0, peak = 0;
  const enriched = await resolver.resolve(orders, async path => {
    active++; peak = Math.max(peak, active);
    await new Promise(resolve => setTimeout(resolve, 5));
    active--;
    return { id: Number(path.split("/").pop()), movie_id: 12 };
  });
  assert.ok(peak <= 4);
  assert.ok(enriched.every(order => order.movie_id === 12));
});
