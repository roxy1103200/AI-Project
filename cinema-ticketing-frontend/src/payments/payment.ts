import { apiRequest } from "../auth/client";

export type PaymentStatus = {
  orderNo: string; paymentNo: string | null; paymentStatus: string; orderStatus: string;
  refundStatus: string | null; environment: string; cashierUrl: string | null; expiresAt: string;
};

export async function openPayment(orderNo: string, token: string, request: typeof apiRequest) {
  const config = await request<{ enabled: boolean; mockEnabled: boolean }>("/api/payments/config", {}, token);
  if (config.enabled) {
    const payment = await request<PaymentStatus>(`/api/orders/${encodeURIComponent(orderNo)}/payment`, { method: "POST" }, token);
    // Stay in this tab so the existing tab-scoped session survives the Alipay round trip.
    if (payment.cashierUrl?.startsWith("/api/payments/checkout/")) window.location.assign(payment.cashierUrl);
    else window.location.assign(`/payment/result?orderNo=${encodeURIComponent(orderNo)}`);
    return;
  }
  if (!config.mockEnabled) throw new Error("支付宝沙箱尚未启用，请待配置完成后再支付");
  await request(`/api/orders/${encodeURIComponent(orderNo)}/pay`, {
    method: "POST", body: JSON.stringify({ paymentNo: `DEMO-${orderNo}` }),
  }, token);
  window.location.assign(`/payment/result?orderNo=${encodeURIComponent(orderNo)}`);
}
