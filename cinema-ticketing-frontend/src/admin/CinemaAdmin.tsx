import { useMemo, useState, type FormEvent } from "react";
import "./movie-admin.css";
import "./cinema-admin.css";

export type AdminCinema = {
  id: number;
  name: string;
  address: string;
  phone?: string | null;
  status?: string | null;
};

type CinemaForm = { name: string; address: string; phone: string; status: string };
type ApiRequest = <T>(path: string, init?: RequestInit, token?: string) => Promise<T>;
type CinemaAdminProps = {
  cinemas: AdminCinema[];
  halls: { cinema_id: number }[];
  isLoading: boolean;
  errorMessage: string;
  token: string;
  request: ApiRequest;
  onRefresh: () => Promise<void>;
};

const PAGE_SIZE = 8;
const EMPTY_FORM: CinemaForm = { name: "", address: "", phone: "", status: "ACTIVE" };

export default function CinemaAdmin({ cinemas, halls, isLoading, errorMessage, token, request, onRefresh }: CinemaAdminProps) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [page, setPage] = useState(1);
  const [editingCinema, setEditingCinema] = useState<AdminCinema | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [form, setForm] = useState<CinemaForm>(EMPTY_FORM);
  const [pendingDelete, setPendingDelete] = useState<AdminCinema | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const counts = useMemo(() => ({
    total: cinemas.length,
    active: cinemas.filter((cinema) => cinema.status === "ACTIVE").length,
    inactive: cinemas.filter((cinema) => cinema.status === "INACTIVE").length,
    halls: halls.length,
  }), [cinemas, halls]);
  const filtered = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase("zh-CN");
    return cinemas.filter((cinema) => {
      const matchesSearch = !keyword || [cinema.name, cinema.address, cinema.phone]
        .some((value) => value?.toLocaleLowerCase("zh-CN").includes(keyword));
      return matchesSearch && (statusFilter === "ALL" || cinema.status === statusFilter);
    });
  }, [cinemas, search, statusFilter]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageCinemas = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function startCreate() {
    setEditingCinema(null);
    setForm({ ...EMPTY_FORM });
    setFeedback(null);
    setIsEditorOpen(true);
  }

  function startEdit(cinema: AdminCinema) {
    setEditingCinema(cinema);
    setForm({ name: cinema.name, address: cinema.address, phone: cinema.phone ?? "", status: cinema.status ?? "ACTIVE" });
    setFeedback(null);
    setIsEditorOpen(true);
  }

  function closeEditor() {
    if (!isSaving) {
      setIsEditorOpen(false);
      setEditingCinema(null);
    }
  }

  async function submitCinema(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = {
      name: form.name.trim(),
      address: form.address.trim(),
      phone: form.phone.trim() || null,
      status: form.status,
    };
    if (!payload.name || !payload.address) {
      setFeedback({ kind: "error", text: "影院名称和地址不能为空。" });
      return;
    }

    setIsSaving(true);
    setFeedback(null);
    try {
      if (editingCinema) {
        await request<void>(`/api/cinemas/${editingCinema.id}`, { method: "PUT", body: JSON.stringify(payload) }, token);
      } else {
        await request<{ id: number }>("/api/cinemas", { method: "POST", body: JSON.stringify(payload) }, token);
      }
      setIsEditorOpen(false);
      setEditingCinema(null);
      try {
        await onRefresh();
        setFeedback({ kind: "success", text: editingCinema ? "影院信息已更新。" : "影院已添加。" });
      } catch {
        setFeedback({ kind: "error", text: "保存已完成，但影院列表刷新失败，请手动刷新。" });
      }
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "保存失败，请稍后重试。" });
    } finally {
      setIsSaving(false);
    }
  }

  async function deleteCinema() {
    if (!pendingDelete) return;
    setDeletingId(pendingDelete.id);
    setFeedback(null);
    try {
      await request<void>(`/api/cinemas/${pendingDelete.id}`, { method: "DELETE" }, token);
      const name = pendingDelete.name;
      setPendingDelete(null);
      try {
        await onRefresh();
        setFeedback({ kind: "success", text: `${name}已删除。` });
      } catch {
        setFeedback({ kind: "error", text: `${name}已删除，但影院列表刷新失败。` });
      }
    } catch (error) {
      setPendingDelete(null);
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "删除失败，请稍后重试。" });
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="movie-admin-page content-width" aria-labelledby="cinema-admin-title">
      <div className="movie-admin-heading">
        <div>
          <p className="eyebrow">CINEMA CONTROL ROOM</p>
          <h1 id="cinema-admin-title">影院管理</h1>
          <p className="movie-admin-lede">维护影院地址、联系方式与营业状态。</p>
        </div>
        <button className="movie-admin-add" type="button" onClick={startCreate}><span aria-hidden="true">＋</span> 添加影院</button>
      </div>

      <div className="movie-admin-stats" aria-label="影院统计">
        <article className="movie-admin-stat"><span>影院总量</span><strong>{counts.total}</strong><small>家影院</small></article>
        <article className="movie-admin-stat"><span>正常营业</span><strong>{counts.active}</strong><small>家影院</small></article>
        <article className="movie-admin-stat"><span>暂停营业</span><strong>{counts.inactive}</strong><small>家影院</small></article>
        <article className="movie-admin-stat"><span>已配置影厅</span><strong>{counts.halls}</strong><small>个影厅</small></article>
      </div>

      <div className="movie-admin-toolbar">
        <label className="movie-admin-search">
          <span aria-hidden="true">⌕</span><span className="sr-only">搜索影院</span>
          <input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索影院名称、地址或电话" />
          {search && <button type="button" aria-label="清除搜索" onClick={() => { setSearch(""); setPage(1); }}>×</button>}
        </label>
        <label className="movie-admin-filter">
          <span>营业状态</span>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }}>
            <option value="ALL">全部状态</option><option value="ACTIVE">正常营业</option><option value="INACTIVE">暂停营业</option>
          </select>
        </label>
        <button className="movie-admin-refresh" type="button" disabled={isLoading} onClick={() => { void onRefresh().catch((error: unknown) => setFeedback({ kind: "error", text: error instanceof Error ? error.message : "影院刷新失败" })); }}>↻ 刷新影院</button>
      </div>

      {feedback && <div className={`movie-admin-feedback ${feedback.kind}`} role="status" aria-live="polite">{feedback.text}</div>}
      {errorMessage && <div className="movie-admin-feedback error" role="alert">{errorMessage}</div>}

      <div className="movie-admin-table-wrap">
        <table className="movie-admin-table cinema-admin-table">
          <thead><tr><th scope="col">影院</th><th scope="col">地址</th><th scope="col">联系电话</th><th scope="col">影厅</th><th scope="col">状态</th><th scope="col"><span className="sr-only">操作</span></th></tr></thead>
          <tbody>
            {pageCinemas.map((cinema) => (
              <tr key={cinema.id}>
                <td><div className="cinema-admin-name"><strong>{cinema.name}</strong><small>编号 #{cinema.id}</small></div></td>
                <td className="cinema-admin-address">{cinema.address}</td>
                <td>{cinema.phone || "—"}</td>
                <td>{halls.filter((hall) => hall.cinema_id === cinema.id).length} 个</td>
                <td><span className={`cinema-admin-status ${cinema.status === "ACTIVE" ? "is-active" : "is-inactive"}`}><i />{cinema.status === "ACTIVE" ? "正常营业" : "暂停营业"}</span></td>
                <td><div className="movie-admin-row-actions"><button type="button" onClick={() => startEdit(cinema)}>编辑</button><button className="danger" type="button" onClick={() => setPendingDelete(cinema)}>删除</button></div></td>
              </tr>
            ))}
            {isLoading && <tr><td className="movie-admin-state" colSpan={6}>正在读取影院…</td></tr>}
            {!isLoading && errorMessage && cinemas.length === 0 && <tr><td className="movie-admin-state" colSpan={6}>影院读取失败，请检查连接后重试。</td></tr>}
            {!isLoading && !errorMessage && pageCinemas.length === 0 && <tr><td className="movie-admin-state" colSpan={6}>{cinemas.length ? "没有符合条件的影院。" : "还没有影院，添加第一家吧。"}</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="movie-admin-table-footer">
        <span>共 {filtered.length} 家影院</span>
        <div className="movie-admin-pagination" aria-label="影院列表分页">
          <button type="button" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>上一页</button>
          <span>第 <strong>{currentPage}</strong> / {pageCount} 页</span>
          <button type="button" disabled={currentPage >= pageCount} onClick={() => setPage(currentPage + 1)}>下一页</button>
        </div>
      </div>

      {isEditorOpen && (
        <div className="movie-admin-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeEditor(); }}>
          <section className="movie-admin-dialog" role="dialog" aria-modal="true" aria-labelledby="cinema-editor-title">
            <div className="movie-admin-dialog-heading">
              <div><p className="eyebrow">CINEMA DETAILS</p><h2 id="cinema-editor-title">{editingCinema ? "编辑影院" : "添加影院"}</h2></div>
              <button className="movie-admin-close" type="button" aria-label="关闭编辑窗口" disabled={isSaving} onClick={closeEditor}>×</button>
            </div>
            <form className="movie-admin-form" onSubmit={(event) => void submitCinema(event)}>
              <label className="wide"><span>影院名称 <b>*</b></span><input autoFocus required maxLength={128} value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="请输入影院名称" /></label>
              <label className="wide"><span>地址 <b>*</b></span><input required maxLength={255} value={form.address} onChange={(event) => setForm((current) => ({ ...current, address: event.target.value }))} placeholder="请输入完整地址" /></label>
              <label><span>联系电话</span><input maxLength={32} value={form.phone} onChange={(event) => setForm((current) => ({ ...current, phone: event.target.value }))} placeholder="例如 021-12345678" /></label>
              <label><span>营业状态 <b>*</b></span><select value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}><option value="ACTIVE">正常营业</option><option value="INACTIVE">暂停营业</option></select></label>
              {feedback?.kind === "error" && <p className="movie-admin-form-error wide" role="alert">{feedback.text}</p>}
              <div className="movie-admin-form-actions wide"><button type="button" disabled={isSaving} onClick={closeEditor}>取消</button><button className="save" type="submit" disabled={isSaving}>{isSaving ? "正在保存…" : editingCinema ? "保存修改" : "创建影院"}</button></div>
            </form>
          </section>
        </div>
      )}

      {pendingDelete && (
        <div className="movie-admin-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && deletingId === null) setPendingDelete(null); }}>
          <section className="movie-admin-confirm" role="alertdialog" aria-modal="true" aria-labelledby="delete-cinema-title" aria-describedby="delete-cinema-description">
            <span className="movie-admin-warning" aria-hidden="true">!</span>
            <p className="eyebrow">REMOVE CINEMA</p>
            <h2 id="delete-cinema-title">确认删除这家影院？</h2>
            <p id="delete-cinema-description">{pendingDelete.name}将被删除。已有影厅的影院无法删除，可以先把营业状态改为“暂停营业”。</p>
            <div className="movie-admin-form-actions"><button type="button" disabled={deletingId !== null} onClick={() => setPendingDelete(null)}>取消</button><button className="delete" type="button" disabled={deletingId !== null} onClick={() => void deleteCinema()}>{deletingId ? "正在删除…" : "确认删除"}</button></div>
          </section>
        </div>
      )}
    </section>
  );
}
