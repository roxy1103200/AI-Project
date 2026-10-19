import type { ApiRequest } from "../admin/movie-save";

type PosterOrder = { screening_id: number; movie_id?: number };
type ScreeningMovie = { id: number; movie_id: number };

function validId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** Older order responses lack movie_id; historical screenings are absent from the selling list. */
export class OrderPosterResolver {
  private readonly movies = new Map<number, number>();
  private readonly pending = new Map<number, Promise<number | undefined>>();

  private movieFor(screeningId: number, request: ApiRequest): Promise<number | undefined> {
    const known = this.movies.get(screeningId);
    if (known !== undefined) return Promise.resolve(known);
    const pending = this.pending.get(screeningId);
    if (pending) return pending;
    const lookup = request<ScreeningMovie>(`/api/screenings/${screeningId}`)
      .then(screening => {
        if (screening?.id !== screeningId || !validId(screening.movie_id)) return undefined;
        this.movies.set(screeningId, screening.movie_id);
        return screening.movie_id;
      })
      .catch(() => undefined)
      .finally(() => this.pending.delete(screeningId));
    this.pending.set(screeningId, lookup);
    return lookup;
  }

  async resolve<T extends PosterOrder>(orders: T[], request: ApiRequest): Promise<T[]> {
    const missing = [...new Set(orders.filter(order => !validId(order.movie_id) && validId(order.screening_id))
      .map(order => order.screening_id))];
    let next = 0;
    // Bound legacy lookups and share results across orders and subsequent refreshes.
    await Promise.all(Array.from({ length: Math.min(4, missing.length) }, async () => {
      while (next < missing.length) await this.movieFor(missing[next++], request);
    }));
    return orders.map(order => {
      const movieId = validId(order.movie_id) ? order.movie_id : this.movies.get(order.screening_id);
      return movieId === undefined || movieId === order.movie_id ? order : { ...order, movie_id: movieId };
    });
  }
}
