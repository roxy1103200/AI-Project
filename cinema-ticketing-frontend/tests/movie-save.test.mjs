import test from "node:test";
import assert from "node:assert/strict";
import { saveMovie, MoviePosterSaveError } from "../src/admin/movie-save.ts";

const values = { title: "测试影片", duration: 90, status: "ON_SHELF" };
const posterFile = new File([new Uint8Array([1, 2, 3])], "poster.png", { type: "image/png" });

test("旧后端不支持图片时，在保存影片信息之前阻止操作", async () => {
  const calls = [];
  await assert.rejects(saveMovie({ values, posterFile, removePoster: false }, async (path) => {
    calls.push(path);
    return { status: "UP" };
  }, "admin"), /影片信息尚未保存/);
  assert.deepEqual(calls, ["/api/health"]);
});

test("新增影片后，图片通过 multipart 上传到新影片 ID", async () => {
  const calls = [];
  const id = await saveMovie({ values, posterFile, removePoster: false }, async (path, init, token) => {
    calls.push({ path, init, token });
    if (path === "/api/health") return { features: { moviePosters: true } };
    if (path === "/api/movies") return { id: 7 };
    assert.equal(init.method, "POST");
    assert.ok(init.body instanceof FormData);
    assert.equal(init.body.get("file").name, "poster.png");
    return { url: "/api/movies/7/poster" };
  }, "admin");
  assert.equal(id, 7);
  assert.deepEqual(calls.map((call) => call.path), ["/api/health", "/api/movies", "/api/movies/7/poster"]);
  assert.equal(calls[2].token, "admin");
});

test("图片失败保留新影片 ID，重试更新原影片并且不重复创建", async () => {
  let savedId;
  await assert.rejects(saveMovie({ values, posterFile, removePoster: false }, async (path) => {
    if (path === "/api/health") return { features: { moviePosters: true } };
    if (path === "/api/movies") return { id: 7 };
    throw new Error("图片存储不可用");
  }, "admin"), (error) => {
    assert.ok(error instanceof MoviePosterSaveError);
    savedId = error.movieId;
    return true;
  });
  const calls = [];
  await saveMovie({ movieId: savedId, values, posterFile, removePoster: false }, async (path, init) => {
    calls.push({ path, method: init?.method });
    return { features: { moviePosters: true } };
  }, "admin");
  assert.deepEqual(calls.slice(1), [
    { path: "/api/movies/7", method: "PUT" },
    { path: "/api/movies/7/poster", method: "POST" },
  ]);
});

test("删除图片检查服务能力，单纯修改文字不调用图片接口", async () => {
  const calls = [];
  const request = async (path, init) => {
    calls.push({ path, method: init?.method });
    return { features: { moviePosters: true } };
  };
  await saveMovie({ movieId: 7, values, posterFile: null, removePoster: true }, request, "admin");
  assert.equal(calls.at(-1).method, "DELETE");
  calls.length = 0;
  await saveMovie({ movieId: 7, values, posterFile: null, removePoster: false }, request, "admin");
  assert.deepEqual(calls, [{ path: "/api/movies/7", method: "PUT" }]);
});
