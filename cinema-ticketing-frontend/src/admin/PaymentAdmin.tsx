import { useEffect, useMemo, useRef, useState } from "react";
import type { ApiRequest } from "./movie-save";
import "./payment-admin.css";

type DateValue = string | number | null;
type Refund = { id: number; refund_no: string; order_no: string; out_trade_no?: string; status: string; attempts: number; last_error_code: string | null; requested_at?: DateValue };
type Payment = { out_trade_no: string; order_no: string; status: string; last_error_code: string | null; last_query_at?: DateValue; close_requested_at?: DateValue };
type Exceptions = { refunds: Refund[]; payments: Payment[] };
type PaymentConfig = { enabled: boolean; mockEnabled: boolean; environment: string };
type RecordKind = "refunds" | "payments";
const PAGE_SIZE = 10;
const AUTOMATIC_LIMIT = 8;
const STATUS_LABELS: Record<string, string> = {
  PENDING: "等待处理", UNKNOWN: "渠道结果待确认", REFUNDED: "退款已确认",
  CREATED: "支付待发起", PAYING: "支付结果待确认", CLOSING: "关闭结果待确认", SUCCESS: "支付已确认", CLOSED: "交易已关闭",
};
function needsManualCheck(refund: Refund) { return refund.status === "UNKNOWN" && refund.attempts >= AUTOMATIC_LIMIT; }
function awaitsAutomaticCheck(refund: Refund) { return refund.attempts < AUTOMATIC_LIMIT && ["PENDING", "UNKNOWN"].includes(refund.status); }
function formatDate(value?: DateValue) {
  if (value === undefined || value === null || value === "") return "暂无记录";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value)) return value.replace("T", " ").slice(0, 16);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未识别" : new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date).replaceAll("/", "-");
}
function StatusBadge({ status, attention = false }: { status: string; attention?: boolean }) {
  return <span className={`payment-status ${attention ? "is-attention" : ""}`}><span aria-hidden="true" />{attention ? "需人工核对" : STATUS_LABELS[status] ?? `待排查（${status}）`}</span>;
}
function ChannelError({ code }: { code: string | null }) {
  return code ? <details className="payment-channel-error"><summary>查看渠道反馈</summary><code>{code}</code></details> : <span className="payment-muted">暂无错误码</span>;
}
function RetryDialog({ refund, busy, error, onClose, onConfirm }: {
  refund: Refund; busy: boolean; error: string; onClose: () => void; onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  return <dialog ref={dialog} className="payment-retry-dialog" aria-labelledby="payment-retry-title" aria-describedby="payment-retry-description"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="payment-dialog-heading"><span className="payment-kicker">人工核对</span><button type="button" className="payment-close" aria-label="关闭核对窗口" disabled={busy} onClick={onClose}>×</button></div>
    <h3 id="payment-retry-title">重新核对这笔退款？</h3><p id="payment-retry-description">系统将使用原退款单号继续向渠道核对，不新建退款单。结果仍以渠道确认为准。</p>
    <dl className="payment-dialog-facts"><div><dt>订单号</dt><dd>{refund.order_no}</dd></div><div><dt>原退款单号</dt><dd>{refund.refund_no}</dd></div><div><dt>已自动核对</dt><dd>{refund.attempts} 次</dd></div></dl>
    {error && <p className="payment-feedback is-error" role="alert">{error}</p>}
    <div className="payment-dialog-actions"><button type="button" className="secondary-button" autoFocus disabled={busy} onClick={onClose}>暂不处理</button><button type="button" className="primary-button" disabled={busy} onClick={onConfirm}>{busy ? "正在核对…" : "确认核对原退款单"}</button></div>
  </dialog>;
}

export default function PaymentAdmin({ request, token }: { request: ApiRequest; token: string }) {
  const [data, setData] = useState<Exceptions | null>(null);
  const [config, setConfig] = useState<PaymentConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState<"success" | "info" | "error">("success");
  const [version, setVersion] = useState(0);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [pending, setPending] = useState<Refund | null>(null);
  const [retryError, setRetryError] = useState("");
  const [kind, setKind] = useState<RecordKind>("refunds");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [priority, setPriority] = useState(true);
  const [page, setPage] = useState(1);
  const mutation = useRef<AbortController | null>(null);

  useEffect(() => {
    setData(null); setConfig(null); setUpdatedAt(null); setNotice(""); setPending(null); setBusy(null);
    return () => { mutation.current?.abort(); mutation.current = null; };
  }, [token]);
  useEffect(() => {
    const controller = new AbortController();
    setError(""); setLoading(true);
    request<Exceptions>("/api/admin/payments/exceptions", { signal: controller.signal }, token)
      .then((value) => { if (!controller.signal.aborted) { setData(value); setUpdatedAt(Date.now()); } })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "记录读取失败，请稍后重试。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    request<PaymentConfig>("/api/payments/config", { signal: controller.signal }, token)
      .then((value) => { if (!controller.signal.aborted) setConfig(value); })
      .catch(() => { if (!controller.signal.aborted) setConfig(null); });
    return () => controller.abort();
  }, [request, token, version]);

  const manualCount = data?.refunds.filter(needsManualCheck).length ?? 0;
  const paymentStatuses = [...new Set(data?.payments.map((payment) => payment.status) ?? [])];
  const rows = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase("zh-CN");
    if (!data) return [];
    const source: (Refund | Payment)[] = kind === "refunds" ? data.refunds : data.payments;
    const filtered = source.filter((record) => {
      const identifiers = [record.order_no, record.last_error_code, "refund_no" in record ? record.refund_no : record.out_trade_no];
      if ("refund_no" in record) identifiers.push(record.out_trade_no ?? "");
      const matchesSearch = !keyword || identifiers.some((value) => value?.toLocaleLowerCase("zh-CN").includes(keyword));
      const matchesFilter = filter === "ALL" || (filter === "MANUAL" ? "refund_no" in record && needsManualCheck(record) : record.status === filter);
      return matchesSearch && matchesFilter;
    });
    return kind === "refunds" && priority ? [...filtered].sort((a, b) => Number(needsManualCheck(b as Refund)) - Number(needsManualCheck(a as Refund))) : filtered;
  }, [data, kind, search, filter, priority]);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageRows = rows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const loadedCount = data ? data[kind].length : 0;
  const environment = !config ? "环境未确认" : config.enabled
    ? config.environment === "sandbox" ? "支付宝沙箱" : config.environment === "production" ? "正式支付环境" : config.environment
    : config.mockEnabled ? "模拟支付已启用" : "支付尚未启用";

  function showRecords(nextKind: RecordKind, nextFilter = "ALL") { setKind(nextKind); setFilter(nextFilter); setSearch(""); setPage(1); }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setNoticeKind("success"); setNotice("单号已复制。"); }
    catch { setNoticeKind("error"); setNotice("复制失败，请选中单号手动复制。"); }
  }
  async function retry() {
    if (!pending || mutation.current || loading) return;
    const controller = new AbortController(); mutation.current = controller;
    setBusy(pending.id); setRetryError(""); setNotice("");
    try {
      const result = await request<{ status: string }>(`/api/admin/refunds/${pending.id}/retry`, { method: "POST", signal: controller.signal }, token);
      if (controller.signal.aborted) return;
      setNoticeKind(result.status === "REFUNDED" ? "success" : "info");
      setNotice(result.status === "REFUNDED" ? "渠道已确认原退款单退款成功，正在更新列表。" : "已核对原退款单，渠道结果仍待确认，正在更新列表。核对受理不代表退款成功。");
      setPending(null); setVersion((value) => value + 1);
    } catch (cause) {
      if (!controller.signal.aborted) setRetryError(`${cause instanceof Error ? cause.message : "核对请求未确认"}。如操作结果不明，请关闭窗口并刷新记录后再处理。`);
    } finally {
      if (mutation.current === controller) { mutation.current = null; if (!controller.signal.aborted) setBusy(null); }
    }
  }

  return <section className="content-width payment-admin-page" aria-labelledby="payment-admin-title">
    <header className="payment-page-heading"><div><p className="eyebrow">PAYMENT RECONCILIATION</p><h1 id="payment-admin-title">支付与退款核对</h1><p className="payment-lede">集中查看未确认记录，优先处理需要人工核对的退款。</p></div>
      <div className="payment-heading-actions"><span className="payment-environment">当前配置 · {environment}</span><button type="button" className="secondary-button" disabled={loading || busy !== null} onClick={() => setVersion((value) => value + 1)}>{loading ? "刷新中…" : "刷新记录"}</button></div></header>
    <div className="payment-overview" aria-label="当前载入记录概览">
      <button type="button" onClick={() => showRecords("refunds")} className={kind === "refunds" && filter !== "MANUAL" ? "is-selected" : ""}><span>待确认退款</span><strong>{data ? data.refunds.length : "—"}</strong><small>本次载入的未确认退款</small></button>
      <button type="button" className={`payment-manual-metric ${kind === "refunds" && filter === "MANUAL" ? "is-selected" : ""}`} onClick={() => showRecords("refunds", "MANUAL")}><span>可人工核对</span><strong>{data ? manualCount : "—"}</strong><small>自动核对已达 {AUTOMATIC_LIMIT} 次</small></button>
      <button type="button" onClick={() => showRecords("payments")} className={kind === "payments" ? "is-selected" : ""}><span>支付核对异常</span><strong>{data ? data.payments.length : "—"}</strong><small>尚未确认成功或关闭</small></button>
    </div>
    <aside className="payment-process-note"><strong>处理说明</strong><p>退款自动核对最多 {AUTOMATIC_LIMIT} 次；渠道结果仍未确认且次数耗尽时，可使用原退款单重新核对。支付异常需结合渠道反馈排查。</p></aside>
    {notice && <p className={`payment-feedback is-${noticeKind}`} role={noticeKind === "error" ? "alert" : "status"}>{notice}</p>}
    {error && <div className="payment-feedback is-error" role="alert"><span>{error}{data ? " 当前仍显示上次成功读取的记录。" : ""}</span><button type="button" disabled={loading || busy !== null} onClick={() => setVersion((value) => value + 1)}>重新读取</button></div>}
    <div className="payment-workspace">
      <div className="payment-record-heading"><div className="payment-record-tabs" role="group" aria-label="记录类型"><button type="button" aria-pressed={kind === "refunds"} onClick={() => showRecords("refunds")}>待确认退款 <span>{data?.refunds.length ?? "—"}</span></button><button type="button" aria-pressed={kind === "payments"} onClick={() => showRecords("payments")}>支付异常 <span>{data?.payments.length ?? "—"}</span></button></div><span className="payment-update-time">{updatedAt ? `更新于 ${formatDate(updatedAt)} · 北京时间` : "尚未读取记录"}</span></div>
      <div className="payment-toolbar"><label className="payment-search"><span className="payment-sr-only">搜索订单、流水或错误码</span><input type="search" value={search} placeholder="搜索订单号、流水号或错误码" onChange={(event) => { setSearch(event.target.value); setPage(1); }} /></label>
        <label className="payment-filter">{kind === "refunds" ? "处理状态" : "支付状态"}<select value={filter} onChange={(event) => { setFilter(event.target.value); setPage(1); }}><option value="ALL">全部状态</option>{kind === "refunds" ? <><option value="MANUAL">需人工核对</option><option value="PENDING">等待处理</option><option value="UNKNOWN">渠道结果待确认</option></> : paymentStatuses.map((status) => <option key={status} value={status}>{STATUS_LABELS[status] ?? status}</option>)}</select></label>
        {kind === "refunds" && <label className="payment-priority"><input type="checkbox" checked={priority} onChange={(event) => { setPriority(event.target.checked); setPage(1); }} />人工核对优先</label>}
        {(search || filter !== "ALL") && <button type="button" className="payment-text-button" onClick={() => { setSearch(""); setFilter("ALL"); setPage(1); }}>清除筛选</button>}
      </div>
      <div className="payment-table-scroll" role="region" aria-label={kind === "refunds" ? "退款核对记录表" : "支付异常记录表"} tabIndex={0}>
        <table className="payment-table" aria-busy={loading}><caption className="payment-sr-only">{kind === "refunds" ? "待确认退款" : "支付核对异常"}，当前筛选 {rows.length} 条</caption><thead><tr><th scope="col">订单 / {kind === "refunds" ? "退款流水" : "支付流水"}</th><th scope="col">核对状态</th><th scope="col">{kind === "refunds" ? "自动核对" : "渠道反馈"}</th><th scope="col">{kind === "refunds" ? "申请时间" : "最近核对"} <small>北京时间</small></th><th scope="col">处理</th></tr></thead>
          <tbody>
            {!data && <tr><td colSpan={5}><div className="payment-empty" role="status"><strong>{loading ? "正在读取核对记录…" : "暂时无法读取记录"}</strong><p>{loading ? "正在获取未确认退款与支付异常。" : "请重新读取，读取失败不代表没有异常。"}</p></div></td></tr>}
            {data && !rows.length && <tr><td colSpan={5}><div className="payment-empty" role="status"><span className="payment-empty-mark" aria-hidden="true">—</span><strong>{loadedCount === 0 ? kind === "refunds" ? "当前没有待确认退款" : "当前没有支付核对异常" : "没有匹配的记录"}</strong><p>{loadedCount === 0 ? "当前返回列表为空，可刷新获取最新状态。" : "试试其他单号，或清除筛选查看已载入记录。"}</p>{loadedCount > 0 && <button type="button" className="payment-text-button" onClick={() => { setSearch(""); setFilter("ALL"); setPage(1); }}>清除筛选</button>}</div></td></tr>}
            {pageRows.map((record) => {
              const refund = "refund_no" in record ? record : null;
              const payment = !refund ? record as Payment : null;
              const manual = refund ? needsManualCheck(refund) : false;
              const flowNo = refund ? refund.refund_no : payment!.out_trade_no;
              return <tr key={refund ? `refund-${refund.id}` : `payment-${flowNo}`} className={manual ? "payment-attention-row" : ""}>
                <td><div className="payment-order-number">{record.order_no}<button type="button" className="payment-copy" aria-label={`复制订单号 ${record.order_no}`} onClick={() => void copy(record.order_no)}>复制</button></div><div className="payment-flow-number"><span>{refund ? "退款单" : "支付单"}</span><code>{flowNo}</code><button type="button" className="payment-copy" aria-label={`复制${refund ? "退款" : "支付"}单号 ${flowNo}`} onClick={() => void copy(flowNo)}>复制</button></div></td>
                <td><StatusBadge status={record.status} attention={manual} />{refund && <ChannelError code={record.last_error_code} />}</td>
                <td>{refund ? <div className="payment-attempts"><strong>{refund.attempts}</strong><span> / {AUTOMATIC_LIMIT} 次</span><small>{manual ? "自动次数已耗尽" : awaitsAutomaticCheck(refund) ? "等待后续自动核对" : "请核实当前状态"}</small></div> : <ChannelError code={record.last_error_code} />}</td>
                <td><time className="payment-date">{formatDate(refund?.requested_at ?? payment?.last_query_at)}</time>{payment?.close_requested_at && <small className="payment-close-time">关单申请 {formatDate(payment.close_requested_at)}</small>}</td>
                <td>{manual ? <button type="button" className="payment-retry-button" disabled={busy !== null || loading} onClick={() => { setRetryError(""); setPending(refund); }}>重新核对</button> : <span className="payment-muted">{refund && awaitsAutomaticCheck(refund) ? "自动处理" : "需人工排查"}</span>}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </div>
      <footer className="payment-list-footer"><span>当前载入 {loadedCount} 条 · 筛选后 {rows.length} 条{loadedCount === 100 ? " · 已达返回上限" : ""}</span><nav className="payment-pagination" aria-label="核对记录分页"><button type="button" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}>上一页</button><span>第 {currentPage} / {pageCount} 页</span><button type="button" disabled={currentPage >= pageCount} onClick={() => setPage(currentPage + 1)}>下一页</button></nav></footer>
    </div>
    <p className="payment-scope-note">每类最多载入最近 100 条记录，搜索、筛选和数量仅针对本次载入的数据；此页不包含完整交易历史。</p>
    {pending && <RetryDialog refund={pending} busy={busy !== null} error={retryError} onClose={() => { if (busy === null) setPending(null); }} onConfirm={() => void retry()} />}
  </section>;
}
