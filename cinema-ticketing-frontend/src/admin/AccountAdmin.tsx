import { useEffect, useState } from "react";
import type { ApiRequest } from "./movie-save";
import "../auth/account-security.css";

type Account = { id: number; username: string; role: string; status: string; session_version: number };
const PAGE_SIZE = 6;

function AccountRow({ account, request, token, refreshed, expanded, toggle, pendingId, setPendingId }: {
  account: Account; request: ApiRequest; token: string; refreshed: () => void;
  expanded: boolean; toggle: () => void; pendingId: number | null; setPendingId: (id: number | null) => void;
}) {
  const [role, setRole] = useState(account.role);
  const [status, setStatus] = useState(account.status);
  const [message, setMessage] = useState("");
  const busy = pendingId === account.id;
  const locked = pendingId !== null;
  const changed = role !== account.role || status !== account.status;
  async function update(revokeOnly = false) {
    setPendingId(account.id); setMessage("");
    try {
      await request(`/api/admin/accounts/${account.id}/${revokeOnly ? "revoke-sessions" : "access"}`, {
        method: revokeOnly ? "POST" : "PATCH",
        body: JSON.stringify({ sessionVersion: account.session_version, ...(!revokeOnly ? { role, status } : {}) }),
      }, token);
      refreshed();
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "操作失败"); }
    finally { setPendingId(null); }
  }
  function toggleEditor() {
    setRole(account.role); setStatus(account.status); setMessage(""); toggle();
  }
  return <article className={`account-security-row${expanded ? " is-expanded" : ""}`}>
    <div className="security-account-summary">
      <div className="security-account-identity">
        <span className="security-account-avatar" aria-hidden="true">{Array.from(account.username)[0]?.toUpperCase() || "U"}</span>
        <div><strong title={account.username}>{account.username}</strong><small>账户 #{account.id}</small></div>
      </div>
      <span className="security-account-role">{account.role === "ADMIN" ? "管理员" : "普通用户"}</span>
      <span className={`security-account-status${account.status === "ACTIVE" ? " is-active" : ""}`}>{account.status === "ACTIVE" ? "已启用" : "已禁用"}</span>
      <button className="secondary-button security-manage-button" type="button" aria-label={`${expanded ? "收起" : "管理"}${account.username}的账户`} aria-expanded={expanded} aria-controls={`account-editor-${account.id}`} disabled={locked} onClick={toggleEditor}>{expanded ? "收起" : "管理"}<span aria-hidden="true">{expanded ? "−" : "+"}</span></button>
    </div>
    {expanded && <div className="security-account-editor" id={`account-editor-${account.id}`}>
      <div className="security-access-fields">
        <label>账户角色<select aria-label={`${account.username}的角色`} value={role} disabled={busy} onChange={(event) => setRole(event.target.value)}><option value="USER">普通用户</option><option value="ADMIN">管理员</option></select></label>
        <label>使用状态<select aria-label={`${account.username}的状态`} value={status} disabled={busy} onChange={(event) => setStatus(event.target.value)}><option value="ACTIVE">启用</option><option value="DISABLED">禁用</option></select></label>
      </div>
      <p className="security-editor-note">变更角色或状态后，该账户的旧登录与 Agent 转接凭证会立即失效。</p>
      <div className="security-editor-actions">
        <button className="primary-button" type="button" disabled={busy || !changed} onClick={() => void update()}>{busy ? "处理中…" : "保存并撤销旧登录"}</button>
        <button className="secondary-button" type="button" disabled={busy || changed} onClick={() => void update(true)}>退出该账户全部设备</button>
      </div>
      {message && <p className="security-inline-error" role="alert">{message} <button className="security-text-button" type="button" disabled={busy} onClick={refreshed}>刷新账户</button></p>}
    </div>}
  </article>;
}

export default function AccountAdmin({ token, request }: { token: string; request: ApiRequest }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [page, setPage] = useState(1);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError(""); setEditingId(null);
    void request<Account[]>("/api/admin/accounts", { signal: abort.signal }, token)
      .then((result) => { if (!abort.signal.aborted) setAccounts(result); })
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "加载失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [request, token, revision]);
  const search = query.trim().toLocaleLowerCase().replace(/^#/, "");
  const filtered = accounts.filter((account) =>
    (account.username.toLocaleLowerCase().includes(search) || String(account.id).includes(search))
    && (statusFilter === "ALL" || account.status === statusFilter));
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const visibleAccounts = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const locked = pendingId !== null;
  return <section className="account-security-admin">
    <header className="security-page-heading">
      <div><h1>账户安全管理</h1><p>管理账户权限、使用状态与设备登录。</p></div>
      <button className="secondary-button" type="button" disabled={loading || locked} onClick={() => setRevision((value) => value + 1)}>{loading ? "加载中…" : "刷新"}</button>
    </header>
    <div className="security-account-panel" aria-busy={loading}>
      <div className="security-list-toolbar">
        <label className="security-search"><span className="security-sr-only">搜索用户名或账户 ID</span><input type="search" placeholder="搜索用户名或账户 ID" value={query} disabled={locked} onChange={(event) => { setQuery(event.target.value); setPage(1); setEditingId(null); }} /></label>
        <label><span className="security-sr-only">筛选账户状态</span><select aria-label="筛选账户状态" value={statusFilter} disabled={locked} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); setEditingId(null); }}><option value="ALL">全部状态</option><option value="ACTIVE">已启用</option><option value="DISABLED">已禁用</option></select></label>
      </div>
      {loading ? <div className="security-list-state" role="status"><strong>正在加载账户</strong><p>请稍候，正在获取最新的账户状态。</p></div>
        : error ? <div className="security-list-state is-error" role="alert"><strong>暂时无法加载</strong><p>{error}</p><button className="secondary-button" type="button" onClick={() => setRevision((value) => value + 1)}>重新加载</button></div>
        : filtered.length === 0 ? <div className="security-list-state" role="status"><strong>{accounts.length ? "没有匹配的账户" : "暂无账户"}</strong><p>{accounts.length ? "试试其他用户名、账户 ID 或状态。" : "账户创建后会显示在这里。"}</p></div>
        : <div className="security-account-list">{visibleAccounts.map((account) =>
          <AccountRow key={`${token}:${account.id}:${account.session_version}`} account={account} request={request} token={token} expanded={editingId === account.id} toggle={() => setEditingId(editingId === account.id ? null : account.id)} pendingId={pendingId} setPendingId={setPendingId} refreshed={() => setRevision((value) => value + 1)} />)}</div>}
      {!loading && !error && <footer className="security-list-footer">
        <span role="status">{query || statusFilter !== "ALL" ? `匹配 ${filtered.length} 个账户` : `共 ${accounts.length} 个账户`}</span>
        {pageCount > 1 && <nav aria-label="账户列表分页"><button className="secondary-button" type="button" disabled={locked || currentPage === 1} onClick={() => { setPage(currentPage - 1); setEditingId(null); }}>上一页</button><span>{currentPage} / {pageCount}</span><button className="secondary-button" type="button" disabled={locked || currentPage === pageCount} onClick={() => { setPage(currentPage + 1); setEditingId(null); }}>下一页</button></nav>}
      </footer>}
    </div>
    <p className="security-page-footnote">系统须保留至少一个可用管理员。最多加载 500 个账户，每页显示 {PAGE_SIZE} 个。</p>
  </section>;
}
