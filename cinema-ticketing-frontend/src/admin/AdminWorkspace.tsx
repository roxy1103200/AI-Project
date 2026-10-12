import { useCallback, useEffect, useState } from "react";
import { useScopedRequest } from "../auth/client";
import type { StoredSession } from "../auth/useTabSession";
import AccountSecurityDialog from "../auth/AccountSecurityDialog";
import AdminLayout from "./AdminLayout";
import AccountAdmin from "./AccountAdmin";
import MovieAdmin, { type AdminMovie } from "./MovieAdmin";
import CinemaAdmin from "./CinemaAdmin";
import HallSeatAdmin from "./HallSeatAdmin";
import MovieReviewAdmin from "./MovieReviewAdmin";
import TicketCheckInAdmin from "./TicketCheckInAdmin";
import SalesReportAdmin from "./SalesReportAdmin";
import AiFeedbackAdmin from "./AiFeedbackAdmin";
import RefundPolicyAdmin from "./RefundPolicyAdmin";
import type { AdminView } from "./routes";

type Cinema = { id: number; name: string; address: string; phone?: string | null; status?: string | null };
type Hall = { id: number; cinema_id: number; name: string; hall_type?: string; status?: string };

/** Own management data and requests independently of the customer's booking workspace. */
export default function AdminWorkspace({ session, view, navigate, signOut, securityRevoked }: {
  session: StoredSession; view: AdminView | null; navigate: (path: string) => void;
  signOut: () => void; securityRevoked: (message: string) => void;
}) {
  const request = useScopedRequest();
  const [movies, setMovies] = useState<AdminMovie[]>([]);
  const [cinemas, setCinemas] = useState<Cinema[]>([]);
  const [halls, setHalls] = useState<Hall[]>([]);
  const [movieLoading, setMovieLoading] = useState(true);
  const [cinemaLoading, setCinemaLoading] = useState(true);
  const [movieError, setMovieError] = useState("");
  const [cinemaError, setCinemaError] = useState("");
  const [imageVersion, setImageVersion] = useState(0);
  const [securityOpen, setSecurityOpen] = useState(false);

  const refreshMovies = useCallback(async (signal?: AbortSignal) => {
    setMovieLoading(true); setMovieError("");
    try {
      const values = await request<AdminMovie[]>("/api/movies", { signal });
      if (!signal?.aborted) { setMovies(values ?? []); setImageVersion((version) => version + 1); }
    } catch (cause) {
      if (!signal?.aborted) { setMovieError(cause instanceof Error ? cause.message : "影片读取失败"); throw cause; }
    } finally { if (!signal?.aborted) setMovieLoading(false); }
  }, [request]);

  const refreshCinemas = useCallback(async (signal?: AbortSignal) => {
    setCinemaLoading(true); setCinemaError("");
    try {
      const [venues, rooms] = await Promise.all([
        request<Cinema[]>("/api/cinemas", { signal }), request<Hall[]>("/api/halls", { signal }),
      ]);
      if (!signal?.aborted) { setCinemas(venues ?? []); setHalls(rooms ?? []); }
    } catch (cause) {
      if (!signal?.aborted) { setCinemaError(cause instanceof Error ? cause.message : "影院读取失败"); throw cause; }
    } finally { if (!signal?.aborted) setCinemaLoading(false); }
  }, [request]);

  useEffect(() => {
    const abort = new AbortController();
    if (view === "movies" || view === "sales-reports") void refreshMovies(abort.signal).catch(() => undefined);
    if (view === "cinemas" || view === "halls" || view === "seats" || view === "sales-reports") void refreshCinemas(abort.signal).catch(() => undefined);
    return () => abort.abort();
  }, [view, refreshMovies, refreshCinemas]);

  const token = session.token;
  let content;
  switch (view) {
    case "accounts": content = <AccountAdmin request={request} token={token} />; break;
    case "movies": content = <MovieAdmin movies={movies} isLoading={movieLoading} errorMessage={movieError} imageVersion={imageVersion} token={token} request={request} onRefresh={() => refreshMovies()} />; break;
    case "cinemas": content = <CinemaAdmin cinemas={cinemas} halls={halls} isLoading={cinemaLoading} errorMessage={cinemaError} token={token} request={request} onRefresh={() => refreshCinemas()} />; break;
    case "halls": case "seats": content = <>{cinemaError && <p className="admin-module-error" role="alert">{cinemaError}</p>}<HallSeatAdmin view={view} cinemas={cinemas} request={request} token={token} onRefresh={() => refreshCinemas()} onSeats={() => navigate("/admin/seats")} /></>; break;
    case "movie-reviews": content = <MovieReviewAdmin request={request} token={token} onChanged={() => refreshMovies()} />; break;
    case "ticket-check-in": content = <TicketCheckInAdmin request={request} token={token} />; break;
    case "sales-reports": content = <>{(movieError || cinemaError) && <p className="admin-module-error" role="alert">{movieError || cinemaError}</p>}<SalesReportAdmin request={request} token={token} cinemas={cinemas} movies={movies} /></>; break;
    case "ai-feedback": content = <AiFeedbackAdmin request={request} token={token} />; break;
    case "refund-policy": content = <RefundPolicyAdmin request={request} token={token} />; break;
    default: content = <section className="admin-not-found"><h1>管理页面不存在</h1><p>请从左侧选择一个管理模块。</p><button className="secondary-button" type="button" onClick={() => navigate("/admin/accounts")}>前往账户安全</button></section>;
  }
  return <AdminLayout view={view} username={session.username} navigate={navigate} signOut={signOut} openSecurity={() => setSecurityOpen(true)}>
    {content}
    {securityOpen && <AccountSecurityDialog token={token} close={() => setSecurityOpen(false)} revoked={securityRevoked} />}
  </AdminLayout>;
}
