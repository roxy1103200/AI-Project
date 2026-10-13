import { useEffect, useState, type FormEvent } from "react";
import { useScopedRequest } from "./client";
import "./account-security.css";

export default function AccountSecurityDialog({ token, close, revoked }: {
  token: string; close: () => void; revoked: (message: string) => void;
}) {
  const request = useScopedRequest();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [section, setSection] = useState<"password" | "devices">("password");
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) close(); };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [busy, close]);

  async function changePassword(event: FormEvent) {
    event.preventDefault(); setError("");
    if (newPassword !== confirmation) { setError("两次输入的新密码不一致"); return; }
    if (new TextEncoder().encode(newPassword).length > 72) { setError("新密码编码后不能超过 72 字节，请缩短密码"); return; }
    setBusy(true);
    try {
      await request("/api/auth/password", { method: "POST", body: JSON.stringify({ currentPassword, newPassword }) }, token);
      revoked("密码已修改，所有设备已退出，请重新登录。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "修改失败，请重试"); }
    finally { setBusy(false); }
  }

  async function logoutAll() {
    setBusy(true); setError("");
    try {
      await request("/api/auth/logout-all", { method: "POST" }, token);
      revoked("所有设备已退出，请重新登录。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "退出失败，请重试"); }
    finally { setBusy(false); }
  }

  return <div className="modal-backdrop auth-backdrop" onClick={() => { if (!busy) close(); }}>
    <section className="auth-modal account-security-dialog" role="dialog" aria-modal="true" aria-labelledby="security-title" onClick={(event) => event.stopPropagation()}>
      <button className="modal-close" type="button" aria-label="关闭账户安全设置" disabled={busy} onClick={close}>×</button>
      <header className="security-dialog-heading"><h2 id="security-title">账户安全</h2><p>管理登录密码与已登录设备。</p></header>
      <div className="security-section-switch" role="group" aria-label="账户安全操作">
        <button type="button" aria-pressed={section === "password"} disabled={busy} onClick={() => { setSection("password"); setError(""); }}>修改密码</button>
        <button type="button" aria-pressed={section === "devices"} disabled={busy} onClick={() => { setSection("devices"); setError(""); }}>设备登录</button>
      </div>
      {section === "password" ? <form className="auth-form" onSubmit={(event) => void changePassword(event)}>
        <label>当前密码<input autoFocus type="password" autoComplete="current-password" placeholder="输入当前登录密码" required maxLength={72} disabled={busy} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
        <label>新密码（至少 8 位）<input type="password" autoComplete="new-password" placeholder="设置至少 8 位的新密码" required minLength={8} maxLength={72} disabled={busy} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
        <label>再次输入新密码<input type="password" autoComplete="new-password" placeholder="再次确认新密码" required minLength={8} maxLength={72} disabled={busy} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        <p className="security-password-note">修改后将退出全部设备，当前设备也需要重新登录，智能 Agent 的旧连接会失效。</p>
        <button className="primary-button" disabled={busy}>{busy ? "处理中…" : "修改密码并退出所有设备"}</button>
      </form> : <div className="security-device-panel">
        <h3>全部设备退出</h3>
        <p>结束此账户在所有设备上的登录，包括当前设备。账户密码不会变更。</p>
        <p className="security-device-note">如果在公共设备上登录后忘记退出，可以在这里统一结束登录。</p>
        <button className="secondary-button" type="button" disabled={busy} onClick={() => void logoutAll()}>{busy ? "处理中…" : "退出全部设备"}</button>
      </div>}
      {error && <p className="modal-feedback error" role="alert">{error}</p>}
    </section>
  </div>;
}
