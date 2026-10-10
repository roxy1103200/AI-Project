import { useEffect, useState, type FormEvent } from "react";
import type { ApiRequest } from "./movie-save";
import "./movie-admin.css";

type Policy = { policy_version: string; cutoff_minutes: number; content: string };

export default function RefundPolicyAdmin({ request, token }: { request: ApiRequest; token: string }) {
  const [minutes, setMinutes] = useState("");
  const [content, setContent] = useState("");
  const [version, setVersion] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    request<Policy>("/api/admin/refund-policy", {}, token).then((value) => {
      if (!mounted) return;
      setMinutes(String(value.cutoff_minutes));
      setContent(value.content.replace(/^退票截止时间为开场前\s*\d+\s*分钟，到达截止时间及之后不能退票。\s*/, ""));
      setVersion(value.policy_version);
    }).catch((error) => { if (mounted) setMessage(error instanceof Error ? error.message : "退票规则读取失败"); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [request, token, reload]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cutoff = Number(minutes);
    if (!minutes.trim() || !Number.isInteger(cutoff) || cutoff < 0 || !content.trim()) { setMessage("请填写非负整数分钟和退票规则说明。"); return; }
    setSaving(true); setMessage("");
    try {
      await request("/api/admin/refund-policy", { method: "PUT", body: JSON.stringify({ cutoffMinutes: cutoff, content: content.trim() }) }, token);
      setMessage("退票规则已保存，立即用于所有订单的后续退票判断。"); setReload((value) => value + 1);
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
    finally { setSaving(false); }
  }
  return <section className="content-width refund-policy-admin">
    <div className="section-heading"><div><p className="eyebrow">REFUND POLICY</p><h2>退票规则</h2></div><button className="secondary-button" type="button" disabled={loading || saving} onClick={() => setReload((value) => value + 1)}>刷新规则</button></div>
    <p className="section-note">全局规则：修改后立即适用于已购及新购订单。历史规则版本保留。</p>
    {message && <p role="status">{message}</p>}
    {loading ? <p>正在读取退票规则…</p> : <form className="refund-policy-form" onSubmit={(event) => void save(event)}>
      <label>退票截止时间（开场前分钟数）<input type="number" min="0" step="1" required value={minutes} disabled={saving} onChange={(event) => setMinutes(event.target.value)} /></label>
      <small>例如 30：开场前 30 分钟及之后无法退票；0：开场时停止退票。</small>
      <label>规则说明<textarea required maxLength={1000} rows={4} value={content} disabled={saving} onChange={(event) => setContent(event.target.value)} /></label>
      <small>截止时间由上方分钟数统一生成；说明中的开场前分钟数会同步更新。</small>
      <p className="section-note">当前版本：{version || "未启用"}</p><button className="primary-button" disabled={saving} type="submit">{saving ? "保存中…" : "保存退票规则"}</button>
    </form>}
  </section>;
}
