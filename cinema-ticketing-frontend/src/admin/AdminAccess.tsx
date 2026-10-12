import { useEffect, useState, type FormEvent } from "react";
import type { StoredSession } from "../auth/useTabSession";
import "./admin-shell.css";

export default function AdminAccess({ session, signIn, signOut, navigate }: {
  session: StoredSession | null; signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void; navigate: (path: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${session ? "需要管理员权限" : "登录管理后台"} · CINEMA`;
    return () => { document.title = previousTitle; };
  }, [session]);
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await signIn(username, password); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "登录失败，请重试"); }
    finally { setBusy(false); setPassword(""); }
  }
  return <main className="admin-access">
    <section className="admin-access-card" aria-labelledby="admin-access-title">
      <div className="brand"><span className="brand-mark">C</span><span>CINEMA / 管理后台</span></div>
      <h1 id="admin-access-title">{session ? "需要管理员权限" : "登录管理后台"}</h1>
      <p>{session ? `当前账户 ${session.username} 是普通用户，无法访问管理模块。` : "使用管理员账户管理影院、票务与账户安全。"}</p>
      {session ? <button className="primary-button" type="button" onClick={signOut}>退出当前账户并重新登录</button> : <form className="auth-form" onSubmit={(event) => void login(event)}>
        <label>用户名<input autoFocus autoComplete="username" value={username} disabled={busy} required onChange={(event) => setUsername(event.target.value)} /></label>
        <label>密码<input type="password" autoComplete="current-password" value={password} disabled={busy} required minLength={8} onChange={(event) => setPassword(event.target.value)} /></label>
        <button className="primary-button" type="submit" disabled={busy}>{busy ? "登录中…" : "登录管理后台"}</button>
      </form>}
      {error && <p className="modal-feedback error" role="alert">{error}</p>}
      <button className="admin-access-back" type="button" disabled={busy} onClick={() => navigate("/")}>返回观影首页</button>
    </section>
  </main>;
}
