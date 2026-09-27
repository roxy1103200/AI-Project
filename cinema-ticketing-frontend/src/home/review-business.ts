export const reviewStatusLabels: Record<string, string> = {
  PENDING: "待审核", APPROVED: "审核通过", REJECTED: "审核拒绝", HIDDEN: "已隐藏",
};
export const reportReasonLabels: Record<string, string> = {
  ABUSE: "辱骂或人身攻击", SPAM: "广告或重复灌水", SPOILER: "恶意剧透", ILLEGAL: "违法违规内容", OTHER: "其他问题",
};
export function reviewTime(value?: string | null) { return value ? value.replace("T", " ").slice(0, 16) : "—"; }
export function isTrue(value?: boolean | number) { return value === true || value === 1; }
export type Review = {
  id: number; user_id: number; username: string; rating: number; content: string; updated_at: string;
  likeCount: number; liked: boolean | number; replyCount: number;
};
export type OwnReply = {
  id: number; review_id: number; content: string; status: string; moderation_note: string; updated_at: string; parent_visible: boolean | number;
};
