export type AdminOrderDetail = {
  order: { id: number; orderNo: string; status: string; totalAmount: string; ticketCount: number; createdAt: string | null; expiresAt: string | null; paidAt: string | null; description: string };
  customer: { id: number | null; username: string | null };
  screening: { id: number | null; movieId: number | null; movieTitle: string | null; cinemaName: string | null; hallName: string | null; status: string | null; durationMinutes: number | null; startTime: string | null; viewingEndTime: string | null };
  tickets: { id: number; seatId: number | null; seatCode: string | null; price: string; status: string; checkedInAt: string | null; checkedInBy: number | null; checkedInByName: string | null }[];
  payment: { paymentNo: string; status: string; channel: string; environment: string; tradeNo: string | null; amount: string; expiresAt: string | null; checkoutIssuedAt: string | null; closeRequestedAt: string | null; closeReason: string | null; paidAt: string | null; confirmedAt: string | null; lastQueryAt: string | null; nextCheckAt: string | null; lastErrorCode: string | null } | null;
  receipts: { paymentNo: string; tradeNo: string | null; amount: string; status: string; channel: string; environment: string; paidAt: string | null }[];
  refunds: { id: number; refundNo: string | null; amount: string; reason: string | null; status: string; channel: string; environment: string; reasonType: string | null; policyVersion: string | null; attempts: number; requestedAt: string | null; refundedAt: string | null; nextCheckAt: string | null; lastErrorCode: string | null }[];
  eligibility: { canCheckIn: boolean; checkInReason: string; canRefund: boolean; refundDeadline: string | null; refundReason: string };
  diagnostics: { configurationMatch: string; storedIdentity: Identity | null; currentIdentity: Identity; issues: { code: string; severity: string; message: string }[] };
  events: { type: string; label: string; at: string; source: string }[];
  dataWarnings: string[]; serverTime: string; timeZone: string;
};
type Identity = { appId: string | null; sellerId: string | null; environment: string | null };

const states: Record<string, string> = {
  UNPAID: "待支付", PAID: "已收款", ISSUED: "已出票", VALID: "有效影票", CANCELLED: "已取消",
  REFUNDING: "退款处理中", REFUNDED: "退款已确认", NOT_STARTED: "未发起支付", INIT: "支付已发起",
  PAYING: "支付待确认", CLOSING: "关单处理中", CLOSED: "支付单已关闭", SUCCESS: "已确认收款",
  PENDING: "等待退款确认", UNKNOWN: "结果待核对", SCHEDULED: "正常排定",
};
export function orderStateLabel(value: string | null | undefined): string {
  return value ? states[value] ?? `待核对状态（${value}）` : "未记录";
}
export function orderQueryError(value: string): string | null {
  const normalized = value.trim();
  return !normalized || normalized.length > 64 || /[\u0000-\u001f\u007f-\u009f]/.test(normalized)
    ? "请输入不超过 64 个字符的完整订单号" : null;
}
export function orderTime(value: string | null): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间资料待核对" : new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(date);
}
export function paymentOrigin(channel?: string | null, environment?: string | null): string {
  const name = channel === "ALIPAY" ? "支付宝" : channel === "MOCK" ? "历史模拟支付" : channel ?? "未发起";
  const scene = environment === "SANDBOX" ? "沙箱" : environment === "MOCK" ? "模拟" : environment;
  return scene ? `${name} · ${scene}` : name;
}

/** Ignores late replies even when a transport does not honor AbortSignal. */
export class OrderQueryRequest {
  private sequence = 0;
  private controller: AbortController | null = null;
  begin() {
    this.cancel();
    const sequence = this.sequence;
    const controller = new AbortController();
    this.controller = controller;
    return { signal: controller.signal, current: () => sequence === this.sequence && !controller.signal.aborted };
  }
  cancel() { this.sequence++; this.controller?.abort(); this.controller = null; }
}
