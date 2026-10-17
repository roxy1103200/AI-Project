/** The public cinema and management workspace have separate navigation trees. */
export const ADMIN_PAGES = [
  { id: "movies", label: "影片管理", group: "影院运营" },
  { id: "cinemas", label: "影院管理", group: "影院运营" },
  { id: "halls", label: "影厅管理", group: "影院运营" },
  { id: "seats", label: "座位管理", group: "影院运营" },
  { id: "ticket-check-in", label: "验票入场", group: "票务服务" },
  { id: "refund-policy", label: "退票规则", group: "票务服务" },
  { id: "payments", label: "支付与退款核对", group: "票务服务" },
  { id: "movie-reviews", label: "影评管理", group: "账户与服务" },
  { id: "ai-feedback", label: "AI 反馈", group: "账户与服务" },
  { id: "accounts", label: "账户安全", group: "账户与服务" },
  { id: "sales-reports", label: "经营报表", group: "经营分析" },
] as const;

export type AdminView = typeof ADMIN_PAGES[number]["id"];

export function isAdminPath(path: string): boolean {
  return path === "/admin" || path.startsWith("/admin/");
}

export function adminView(path: string): AdminView | null {
  const normalized = path.replace(/\/+$/, "");
  if (normalized === "/admin") return "accounts";
  return ADMIN_PAGES.find((page) => normalized === `/admin/${page.id}`)?.id ?? null;
}

/** Only use the role returned by the existing server-backed session hook. */
export function canOpenAdmin(role?: string): boolean {
  return role === "ADMIN";
}
