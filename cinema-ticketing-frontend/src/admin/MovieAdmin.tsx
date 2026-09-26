import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import "./movie-admin.css";
import { saveMovie, MoviePosterSaveError } from "./movie-save";
import MovieScheduleFields, { type DraftScreening, type ScheduleHall, type ScheduleCinema } from "./MovieScheduleFields";

export type AdminMovie = {
  id: number;
  title: string;
  description?: string | null;
  duration?: number | null;
  release_date?: string | null;
  sale_start_time?: string | null;
  sale_end_time?: string | null;
  sales_status?: string;
  future_screening_count?: number;
  director?: string | null;
  actors?: string | null;
  genre?: string | null;
  status?: string | null;
};

type MovieForm = {
  title: string;
  description: string;
  duration: string;
  release_date: string;
  sale_start_time: string;
  sale_end_time: string;
  director: string;
  actors: string;
  genre: string;
  status: string;
};

type ApiRequest = <T>(path: string, init?: RequestInit, token?: string) => Promise<T>;

type MovieAdminProps = {
  movies: AdminMovie[];
  isLoading: boolean;
  errorMessage: string;
  imageVersion: number;
  token: string;
  request: ApiRequest;
  onRefresh: () => Promise<void>;
};

const PAGE_SIZE = 8;
const EMPTY_FORM: MovieForm = {
  title: "",
  description: "",
  duration: "",
  release_date: "",
  sale_start_time: "",
  sale_end_time: "",
  director: "",
  actors: "",
  genre: "",
  status: "UPCOMING",
};

const STATUS_LABELS: Record<string, string> = {
  UPCOMING: "即将上映",
  ON_SHELF: "正在上映",
  ON_SHOW: "正在上映",
  OFFLINE: "已下线",
};

function formFromMovie(movie?: AdminMovie): MovieForm {
  if (!movie) return { ...EMPTY_FORM };
  return {
    title: movie.title ?? "",
    description: movie.description ?? "",
    duration: movie.duration == null ? "" : String(movie.duration),
    release_date: movie.release_date?.slice(0, 10) ?? "",
    sale_start_time: movie.sale_start_time?.slice(0, 19) ?? "",
    sale_end_time: movie.sale_end_time?.slice(0, 19) ?? "",
    director: movie.director ?? "",
    actors: movie.actors ?? "",
    genre: movie.genre ?? "",
    status: movie.status === "ON_SHOW" ? "ON_SHELF" : movie.status ?? "UPCOMING",
  };
}

function statusLabel(status?: string | null): string {
  if (!status) return "未设置";
  return STATUS_LABELS[status] ?? status;
}

function statusClass(status?: string | null): string {
  if (status === "ON_SHELF" || status === "ON_SHOW") return "is-showing";
  if (status === "OFFLINE") return "is-offline";
  return "is-upcoming";
}

function displayDate(value?: string | null): string {
  if (!value) return "未设置";
  const date = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export default function MovieAdmin({ movies, isLoading, errorMessage, imageVersion, token, request, onRefresh }: MovieAdminProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [page, setPage] = useState(1);
  const [editingMovie, setEditingMovie] = useState<AdminMovie | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [form, setForm] = useState<MovieForm>(EMPTY_FORM);
  const [pendingDelete, setPendingDelete] = useState<AdminMovie | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [posterFile, setPosterFile] = useState<File | null>(null);
  const [removePoster, setRemovePoster] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const posterInput = useRef<HTMLInputElement>(null);
  const [scheduleSlots, setScheduleSlots] = useState<DraftScreening[]>([]);
  const [scheduleHalls, setScheduleHalls] = useState<ScheduleHall[]>([]);
  const [scheduleCinemas, setScheduleCinemas] = useState<ScheduleCinema[]>([]);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleError, setScheduleError] = useState("");
  const [scheduleVersion, setScheduleVersion] = useState(0);
  const [editorTab, setEditorTab] = useState<"basic" | "release" | "schedule">("basic");

  useEffect(() => {
    if (!isCreating) return;
    let mounted = true;
    setScheduleLoading(true);
    setScheduleError("");
    const load = async () => {
      try {
        const [halls, cinemas, slots] = await Promise.all([
          request<ScheduleHall[]>("/api/halls", {}, token),
          request<ScheduleCinema[]>("/api/cinemas", {}, token),
          editingMovie ? request<(Omit<DraftScreening, "hall_id" | "price"> & { hall_id: number; price: number | string })[]>(`/api/movies/${editingMovie.id}/screenings`, {}, token) : Promise.resolve([]),
        ]);
        if (!mounted) return;
        setScheduleHalls(halls);
        setScheduleCinemas(cinemas);
        setScheduleSlots(slots.map((slot) => ({ ...slot, hall_id: String(slot.hall_id), price: String(slot.price), start_time: slot.start_time.slice(0, 19), end_time: slot.end_time.slice(0, 19) })));
      } catch (error) {
        if (mounted) setScheduleError(error instanceof Error ? error.message : "排期读取失败");
      } finally { if (mounted) setScheduleLoading(false); }
    };
    void load();
    return () => { mounted = false; };
  }, [isCreating, editingMovie?.id, scheduleVersion, request, token]);

  useEffect(() => {
    if (!posterFile) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(posterFile);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [posterFile]);

  const counts = useMemo(() => ({
    total: movies.length,
    showing: movies.filter((movie) => (movie.status === "ON_SHELF" || movie.status === "ON_SHOW") && movie.sales_status === "AVAILABLE").length,
    pending: movies.filter((movie) => movie.sales_status === "NO_SCREENINGS" && movie.status !== "UPCOMING" && movie.status !== "OFFLINE").length,
    upcoming: movies.filter((movie) => movie.status !== "OFFLINE" && (movie.status === "UPCOMING" || movie.sales_status === "NOT_STARTED")).length,
    offline: movies.filter((movie) => movie.status === "OFFLINE").length,
  }), [movies]);

  const filteredMovies = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase("zh-CN");
    return movies.filter((movie) => {
      const matchesSearch = !normalizedSearch || [movie.title, movie.director, movie.actors, movie.genre]
        .some((value) => value?.toLocaleLowerCase("zh-CN").includes(normalizedSearch));
      const matchesStatus = statusFilter === "ALL"
        || (statusFilter === "PENDING" && movie.sales_status === "NO_SCREENINGS" && movie.status !== "UPCOMING" && movie.status !== "OFFLINE")
        || (statusFilter === "ON_SHELF" && (movie.status === "ON_SHELF" || movie.status === "ON_SHOW") && movie.sales_status === "AVAILABLE")
        || (statusFilter === "UPCOMING" && movie.status !== "OFFLINE" && (movie.status === "UPCOMING" || movie.sales_status === "NOT_STARTED"))
        || (statusFilter !== "ON_SHELF" && statusFilter !== "PENDING" && statusFilter !== "UPCOMING" && movie.status === statusFilter);
      return matchesSearch && matchesStatus;
    });
  }, [movies, search, statusFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredMovies.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageMovies = filteredMovies.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function startCreate() {
    setEditorTab("basic");
    setScheduleSlots([]);
    setScheduleLoading(true);
    setEditingMovie(null);
    setForm({ ...EMPTY_FORM });
    setFeedback(null);
    setPosterFile(null);
    setRemovePoster(false);
    setIsCreating(true);
  }

  function startEdit(movie: AdminMovie) {
    setEditorTab("basic");
    setScheduleSlots([]);
    setScheduleLoading(true);
    setEditingMovie(movie);
    setForm(formFromMovie(movie));
    setFeedback(null);
    setPosterFile(null);
    setRemovePoster(false);
    setIsCreating(true);
  }

  function closeEditor() {
    if (isSaving) return;
    setIsCreating(false);
    setEditingMovie(null);
    setPosterFile(null);
    setRemovePoster(false);
  }

  function selectPoster(file?: File) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024 || file.size === 0) {
      setFeedback({ kind: "error", text: "请选择不超过 5 MB 的图片。" });
      if (posterInput.current) posterInput.current.value = "";
      return;
    }
    if (file.type && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setFeedback({ kind: "error", text: "仅支持 JPG、PNG 或 WebP 图片。" });
      if (posterInput.current) posterInput.current.value = "";
      return;
    }
    setPosterFile(file);
    setRemovePoster(false);
    setFeedback(null);
  }

  async function submitMovie(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (scheduleLoading || scheduleError) return;
    if ((!!form.sale_start_time !== !!form.sale_end_time) || (form.sale_start_time && form.sale_end_time <= form.sale_start_time)) {
      setEditorTab("release");
      setFeedback({ kind: "error", text: "请填写完整上架周期，截止时间必须晚于开始时间。" });
      return;
    }
    if (!form.title.trim()) {
      setEditorTab("basic");
      setFeedback({ kind: "error", text: "影片名称不能为空。" });
      return;
    }
    const duration = Number(form.duration);
    if (!Number.isInteger(duration) || duration < 1) {
      setEditorTab("basic");
      setFeedback({ kind: "error", text: "片长请填写大于 0 的整数分钟数。" });
      return;
    }

    if (scheduleSlots.some((slot) => !slot.hall_id || !slot.start_time || !slot.end_time || !Number.isFinite(Number(slot.price)) || Number(slot.price) <= 0)) {
      setEditorTab("schedule");
      setFeedback({ kind: "error", text: "请完整填写每个场次的影厅、开场时间和票价，或移除未填写的场次。" });
      return;
    }
    const payload = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      duration,
      release_date: form.release_date || null,
      sale_start_time: form.sale_start_time || null,
      sale_end_time: form.sale_end_time || null,
      screenings: scheduleSlots.map((slot) => ({ id: slot.id, hall_id: Number(slot.hall_id), start_time: slot.start_time, end_time: slot.end_time, price: Number(slot.price), status: slot.status })),
      director: form.director.trim() || null,
      actors: form.actors.trim() || null,
      genre: form.genre.trim() || null,
      status: form.status,
    };

    setIsSaving(true);
    setFeedback(null);
    try {
      await saveMovie({ movieId: editingMovie?.id, values: payload, posterFile, removePoster }, request, token);
    } catch (error) {
      if (error instanceof MoviePosterSaveError) {
        setEditingMovie({ id: error.movieId, ...payload });
        // Metadata and schedules have committed; reload generated IDs before retrying the poster.
        setScheduleVersion((version) => version + 1);
        try { await onRefresh(); } catch { /* 保留表单与图片，供用户重试。 */ }
      }
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "影片保存失败，请稍后重试。" });
      setIsSaving(false);
      return;
    }

    setIsCreating(false);
    setEditingMovie(null);
    setPosterFile(null);
    setRemovePoster(false);
    try {
      await onRefresh();
      setFeedback({ kind: "success", text: editingMovie ? "影片信息与图片已更新。" : "影片已添加到片库。" });
    } catch {
      setFeedback({ kind: "error", text: "保存已完成，但片库刷新失败，请稍后手动刷新。" });
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteMovie() {
    if (!pendingDelete) return;
    setDeletingId(pendingDelete.id);
    setFeedback(null);
    try {
      await request<void>(`/api/movies/${pendingDelete.id}`, { method: "DELETE" }, token);
      const title = pendingDelete.title;
      setPendingDelete(null);
      try {
        await onRefresh();
        setFeedback({ kind: "success", text: `《${title}》已从片库删除。` });
      } catch {
        setFeedback({ kind: "error", text: `《${title}》已删除，但片库刷新失败，请稍后手动刷新。` });
      }
    } catch (error) {
      setPendingDelete(null);
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "删除失败，请稍后重试。" });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="movie-admin-page content-width" aria-labelledby="admin-page-title">
      <div className="movie-admin-heading">
        <div>
          <p className="eyebrow">CINEMA CONTROL ROOM</p>
          <h1 id="admin-page-title">影片管理</h1>
          <p className="movie-admin-lede">维护片库信息与上映状态，更新内容会同步到观众片单。</p>
        </div>
        <button className="movie-admin-add" type="button" onClick={startCreate}>
          <span aria-hidden="true">＋</span> 添加影片
        </button>
      </div>

      <div className="movie-admin-stats" aria-label="影片统计">
        <article className="movie-admin-stat"><span>片库总量</span><strong>{counts.total}</strong><small>部影片</small></article>
        <article className="movie-admin-stat"><span>正在上映</span><strong>{counts.showing}</strong><small>部影片</small></article>
        <article className="movie-admin-stat"><span>待排期</span><strong>{counts.pending}</strong><small>部影片</small></article>
        <article className="movie-admin-stat"><span>即将上映</span><strong>{counts.upcoming}</strong><small>部影片</small></article>
        <article className="movie-admin-stat"><span>已下线</span><strong>{counts.offline}</strong><small>部影片</small></article>
      </div>

      <div className="movie-admin-toolbar">
        <label className="movie-admin-search">
          <span aria-hidden="true">⌕</span>
          <span className="sr-only">搜索影片</span>
          <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索片名、导演、主演或类型" />
          {search && <button type="button" aria-label="清除搜索" onClick={() => { setSearch(""); setPage(1); }}>×</button>}
        </label>
        <label className="movie-admin-filter">
          <span>上映状态</span>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }}>
            <option value="ALL">全部状态</option>
            <option value="ON_SHELF">正在上映</option>
            <option value="PENDING">待排期</option>
            <option value="UPCOMING">即将上映</option>
            <option value="OFFLINE">已下线</option>
          </select>
        </label>
        <button className="movie-admin-refresh" type="button" disabled={isLoading} onClick={() => { void onRefresh().catch((error: unknown) => setFeedback({ kind: "error", text: error instanceof Error ? error.message : "片库刷新失败，请稍后重试。" })); }}>
          <span aria-hidden="true">↻</span> 刷新片库
        </button>
      </div>

      {feedback && <div className={`movie-admin-feedback ${feedback.kind}`} role="status" aria-live="polite">{feedback.text}</div>}
      {errorMessage && <div className="movie-admin-feedback error" role="alert">{errorMessage}</div>}

      <div className="movie-admin-table-wrap">
        <table className="movie-admin-table">
          <thead><tr><th scope="col">影片</th><th scope="col">类型</th><th scope="col">上映日期</th><th scope="col">片长</th><th scope="col">状态</th><th scope="col"><span className="sr-only">操作</span></th></tr></thead>
          <tbody>
            {pageMovies.map((movie) => (
              <tr key={movie.id}>
                <td>
                  <div className="movie-admin-title-cell">
                    <span className="movie-admin-poster" aria-hidden="true" style={{ backgroundImage: `url("/api/movies/${movie.id}/poster?v=${imageVersion}"), linear-gradient(155deg, #37303a, #22262f 70%)` }}>{movie.title.slice(0, 1)}</span>
                    <span className="movie-admin-title-copy"><strong>{movie.title}</strong><small>{movie.director ? `导演：${movie.director}` : `影片编号 #${movie.id}`}</small></span>
                  </div>
                </td>
                <td>{movie.genre || "—"}</td>
                <td>{displayDate(movie.release_date)}</td>
                <td>{movie.duration ? `${movie.duration} 分钟` : "—"}</td>
                <td><span className={`movie-admin-status ${statusClass(movie.sales_status === "NOT_STARTED" ? "UPCOMING" : movie.status)}`}><i />{movie.sales_status === "NOT_STARTED" ? "待上架" : statusLabel(movie.status)}</span><small className="movie-admin-sales-note">{movie.sales_status === "NO_SCREENINGS" ? "待排期" : movie.sales_status === "NOT_STARTED" ? Number(movie.future_screening_count) > 0 ? `已排 ${movie.future_screening_count} 场，未到上架时间` : "未到上架时间，尚未排期" : movie.sales_status === "ENDED" ? "上架已截止" : movie.sales_status === "AVAILABLE" ? "可订购" : ""}</small></td>
                <td><div className="movie-admin-row-actions"><button type="button" onClick={() => startEdit(movie)}>编辑</button><button type="button" className="danger" onClick={() => setPendingDelete(movie)}>删除</button></div></td>
              </tr>
            ))}
            {isLoading && <tr><td className="movie-admin-state" colSpan={6}>正在同步片库…</td></tr>}
            {!isLoading && errorMessage && movies.length === 0 && <tr><td className="movie-admin-state" colSpan={6}>片库读取失败，请修复连接后点击“刷新片库”重试。</td></tr>}
            {!isLoading && !errorMessage && pageMovies.length === 0 && <tr><td className="movie-admin-state" colSpan={6}>{movies.length ? "没有找到符合条件的影片，试试其他关键词或状态。" : "片库还是空的，添加第一部影片吧。"}</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="movie-admin-table-footer">
        <span>共 {filteredMovies.length} 部影片</span>
        <div className="movie-admin-pagination" aria-label="影片列表分页">
          <button type="button" disabled={currentPage <= 1} onClick={() => setPage(Math.max(1, currentPage - 1))}>上一页</button>
          <span>第 <strong>{currentPage}</strong> / {pageCount} 页</span>
          <button type="button" disabled={currentPage >= pageCount} onClick={() => setPage(Math.min(pageCount, currentPage + 1))}>下一页</button>
        </div>
      </div>

      {isCreating && (
        <div className="movie-admin-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeEditor(); }}>
          <section className={"movie-admin-dialog " + (editorTab === "schedule" ? "is-schedule-editor" : "")} role="dialog" aria-modal="true" aria-labelledby="movie-editor-title">
            <div className="movie-admin-dialog-heading">
              <div><p className="eyebrow">MOVIE DETAILS</p><h2 id="movie-editor-title">{editingMovie ? "编辑影片" : "添加影片"}</h2></div>
              <button className="movie-admin-close" type="button" aria-label="关闭编辑窗口" disabled={isSaving} onClick={closeEditor}>×</button>
            </div>
            <nav className="movie-editor-tabs" aria-label="编辑内容">
              {([{ id: "basic", label: "影片资料" }, { id: "release", label: "上架设置" }, { id: "schedule", label: "场次排期" }] as const).map((tab) => <button key={tab.id} type="button" aria-pressed={editorTab === tab.id} className={editorTab === tab.id ? "active" : ""} onClick={() => setEditorTab(tab.id)}>{tab.label}{tab.id === "schedule" && <small>{scheduleSlots.length}</small>}</button>)}
            </nav>
            <form className="movie-admin-form movie-editor-form" noValidate onSubmit={(event) => void submitMovie(event)}>
              <div className="movie-editor-panel" hidden={editorTab !== "basic"}>
                <label className="wide"><span>影片名称 <b>*</b></span><input autoFocus required maxLength={128} value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} placeholder="请输入影片名称" /></label>
                <label><span>片长（分钟） <b>*</b></span><input required type="number" min="1" step="1" placeholder="例如 120" value={form.duration} onChange={(event) => setForm((current) => ({ ...current, duration: event.target.value }))} /></label>
                <label><span>影片类型</span><input maxLength={128} value={form.genre} onChange={(event) => setForm((current) => ({ ...current, genre: event.target.value }))} /></label>
                <label><span>上映日期</span><input type="date" value={form.release_date} onChange={(event) => setForm((current) => ({ ...current, release_date: event.target.value }))} /></label>
                <label><span>导演</span><input maxLength={128} value={form.director} onChange={(event) => setForm((current) => ({ ...current, director: event.target.value }))} /></label>
                <details className="movie-editor-more wide"><summary>主演与影片简介</summary><div className="movie-editor-more-content">
                  <label className="wide"><span>主演</span><input maxLength={512} value={form.actors} onChange={(event) => setForm((current) => ({ ...current, actors: event.target.value }))} /></label>
                  <label className="wide"><span>影片简介</span><textarea rows={3} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} /></label>
                </div></details>
                <details className="movie-editor-more wide"><summary>电影海报{posterFile ? " · 已选择新图片" : removePoster ? " · 待移除" : ""}</summary>
              <div className="movie-admin-image-field wide">
                <span>电影图片</span>
                <div className="movie-admin-image-control">
                  <div className="movie-admin-image-preview" role="img" aria-label="电影图片预览" style={{ backgroundImage: previewUrl ? `url("${previewUrl}")` : editingMovie && !removePoster ? `url("/api/movies/${editingMovie.id}/poster?v=${imageVersion}"), linear-gradient(155deg, #37303a, #22262f)` : "linear-gradient(155deg, #37303a, #22262f)" }} />
                  <div className="movie-admin-image-options">
                    <input ref={posterInput} type="file" disabled={isSaving} accept="image/jpeg,image/png,image/webp" onChange={(event) => selectPoster(event.target.files?.[0])} aria-label="选择电影图片" />
                    <small>支持 JPG、PNG、WebP，最大 5 MB。选择新图后保存即可替换。</small>
                    {editingMovie && <button type="button" disabled={isSaving} onClick={() => { setPosterFile(null); setRemovePoster(true); if (posterInput.current) posterInput.current.value = ""; }}>移除当前图片</button>}
                    {removePoster && <small>保存后将移除已上传的图片。</small>}
                  </div>
                </div>
              </div>

                </details>
              </div>
              <div className="movie-editor-panel" hidden={editorTab !== "release"}>
                <label className="wide"><span>上映状态 <b>*</b></span><select value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}><option value="UPCOMING">即将上映</option><option value="ON_SHELF">正在上映</option><option value="OFFLINE">已下线</option></select></label>
                <label><span>上架开始时间</span><input type="datetime-local" step="1" value={form.sale_start_time} onChange={(event) => setForm((current) => ({ ...current, sale_start_time: event.target.value }))} /></label>
                <label><span>上架截止时间</span><input type="datetime-local" step="1" value={form.sale_end_time} onChange={(event) => setForm((current) => ({ ...current, sale_end_time: event.target.value }))} /></label>
                <p className="movie-admin-period-note wide">北京时间，开始时生效、截止时停止售票。两项均留空为不限时。上架后仍需安排场次才能订购。</p>
              </div>
              <div className="movie-editor-panel" hidden={editorTab !== "schedule"}>
                <div className="movie-editor-context wide"><strong>{form.title || "未命名影片"}</strong><span>{Number(form.duration) > 0 ? "每场占用 " + (Number(form.duration) + 20) + " 分钟（含 20 分钟周转）" : "请先填写影片片长"}</span></div>
                <MovieScheduleFields slots={scheduleSlots} halls={scheduleHalls} cinemas={scheduleCinemas} duration={Number(form.duration)} loading={scheduleLoading} error={scheduleError} disabled={isSaving} onChange={setScheduleSlots} movieId={editingMovie?.id} movieTitle={form.title} saleStart={form.sale_start_time} saleEnd={form.sale_end_time} token={token} request={request} />
              </div>
              <div className="movie-editor-footer">
                {feedback?.kind === "error" && <p className="movie-admin-form-error" role="alert">{feedback.text}</p>}
                <div className="movie-admin-form-actions"><button type="button" disabled={isSaving} onClick={closeEditor}>取消</button><button className="save" type="submit" disabled={isSaving || scheduleLoading || !!scheduleError}>{isSaving ? "正在保存…" : "保存全部修改"}</button></div>
              </div>
            </form>
          </section>
        </div>
      )}

      {pendingDelete && (
        <div className="movie-admin-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && deletingId === null) setPendingDelete(null); }}>
          <section className="movie-admin-confirm" role="alertdialog" aria-modal="true" aria-labelledby="delete-movie-title" aria-describedby="delete-movie-description">
            <span className="movie-admin-warning" aria-hidden="true">!</span>
            <p className="eyebrow">REMOVE FROM CATALOG</p>
            <h2 id="delete-movie-title">确认删除这部影片？</h2>
            <p id="delete-movie-description">《{pendingDelete.title}》将从片库中移除。若影片已关联放映场次，系统会阻止删除并显示原因。</p>
            <div className="movie-admin-form-actions"><button type="button" disabled={deletingId !== null} onClick={() => setPendingDelete(null)}>取消</button><button className="delete" type="button" disabled={deletingId !== null} onClick={() => void deleteMovie()}>{deletingId ? "正在删除…" : "确认删除"}</button></div>
          </section>
        </div>
      )}
    </section>
  );
}
