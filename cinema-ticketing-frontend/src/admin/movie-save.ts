export type ApiRequest = <T>(path: string, init?: RequestInit, token?: string) => Promise<T>;

type MovieSaveInput = {
  movieId?: number;
  values: Record<string, unknown>;
  posterFile: File | null;
  removePoster: boolean;
};

export class MoviePosterSaveError extends Error {
  readonly movieId: number;

  constructor(movieId: number, cause: unknown) {
    const detail = cause instanceof Error ? cause.message : "请稍后重试";
    super(`影片信息已保存，但图片处理失败：${detail}。可以在当前窗口再次保存重试。`);
    this.name = "MoviePosterSaveError";
    this.movieId = movieId;
  }
}

export async function saveMovie(input: MovieSaveInput, request: ApiRequest, token: string): Promise<number> {
  if (input.posterFile || input.removePoster) {
    const health = await request<{ features?: { moviePosters?: boolean } }>("/api/health");
    if (health.features?.moviePosters !== true) {
      throw new Error("图片服务暂不可用，影片信息尚未保存。请更新并重启后端服务后重试。");
    }
  }

  const init = { body: JSON.stringify(input.values) };
  let movieId = input.movieId;
  if (movieId == null) {
    const created = await request<{ id: number }>("/api/movies", { ...init, method: "POST" }, token);
    movieId = created.id;
  } else {
    await request<void>(`/api/movies/${movieId}`, { ...init, method: "PUT" }, token);
  }

  try {
    if (input.posterFile) {
      const body = new FormData();
      body.append("file", input.posterFile);
      await request(`/api/movies/${movieId}/poster`, { method: "POST", body }, token);
    } else if (input.removePoster) {
      await request(`/api/movies/${movieId}/poster`, { method: "DELETE" }, token);
    }
  } catch (error) {
    throw new MoviePosterSaveError(movieId, error);
  }
  return movieId;
}
