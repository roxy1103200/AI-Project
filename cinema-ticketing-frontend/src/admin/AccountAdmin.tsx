import { useEffect, useState } from "react";
import type { ApiRequest } from "./movie-save";
import "../auth/account-security.css";

type Account = { id: number; username: string; role: string; status: string; session_version: number };

function AccountRow({ account, request, token, refreshed }: {
  account: Account; request: ApiRequest; token: string; refreshed: () => void;
}) {
  const [role, setRole] = useState(account.role);
  const [status, setStatus] = useState(account.status);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const changed = role !== account.role || status !== account.status;
  async function update(revokeOnly = false) {
    setBusy(true); setMessage("");
    try {
      await request(`/api/admin/accounts/${account.id}/${revokeOnly ? "revoke-sessions" : "access"}`, {
        method: revokeOnly ? "POST" : "PATCH",
        body: JSON.stringify({ sessionVersion: account.session_version, ...(!revokeOnly ? { role, status } : {}) }),
      }, token);
      refreshed();
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "操作失败"); }
    finally { setBusy(false); }
  }
  return <article className="account-security-row">
    <div><strong>{account.username}</strong><small>账户 #{account.id}</small></div>
    <label>角色<select aria-label={`${account.username}的角色`} value={role} disabled={busy} onChange={(event) => setRole(event.target.value)}><option value="USER">普通用户</option><option value="ADMIN">管理员</option></select></label>
    <label>状态<select aria-label={`${account.username}的状态`} value={status} disabled={busy} onChange={(event) => setStatus(event.target.value)}><option value="ACTIVE">启用</option><option value="DISABLED">禁用</option></select></label>
    <button className="primary-button" type="button" disabled={busy || !changed} onClick={() => void update()}>保存并撤销旧登录</button>
    <button className="secondary-button" type="button" disabled={busy || changed} onClick={() => void update(true)}>退出该账户全部设备</button>
    {message && <p role="alert">{message} <button type="button" disabled={busy} onClick={refreshed}>刷新账户</button></p>}
  </article>;
}

export default function AccountAdmin({ token, request }: { token: string; request: ApiRequest }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError("");
    void request<Account[]>("/api/admin/accounts", { signal: abort.signal }, token).then(setAccounts)
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "加载失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [request, token, revision]);
  return <section className="account-security-admin">
    <header><h1>账户安全管理</h1><button className="secondary-button" type="button" disabled={loading} onClick={() => setRevision((value) => value + 1)}>刷新</button></header>
    <p>变更角色或状态会立即撤销该账户的全部旧登录与 Agent 转接凭证。系统须保留至少一个可用管理员。</p>
    {loading ? <p role="status">正在加载账户…</p> : error ? <p role="alert">{error}</p> : accounts.map((account) =>
      <AccountRow key={`${account.id}:${account.session_version}`} account={account} request={request} token={token} refreshed={() => setRevision((value) => value + 1)} />)}
    <p>最多显示 500 个账户。</p>
  </section>;
}
