import type { ComponentProps } from "react";

type IconProps = Pick<ComponentProps<"span">, "className" | "aria-hidden">;

function Glyph({ children, className = "" }: IconProps & { children: string }) {
  return <span className={`assistant-icon ${className}`} aria-hidden="true">{children}</span>;
}

export function ReaderIcon(props: IconProps) { return <Glyph {...props}>▤</Glyph>; }
export function BookmarkIcon(props: IconProps) { return <Glyph {...props}>▱</Glyph>; }
export function ChevronDownIcon(props: IconProps) { return <Glyph {...props}>⌄</Glyph>; }
export function Cross2Icon(props: IconProps) { return <Glyph {...props}>×</Glyph>; }
export function PaperPlaneIcon(props: IconProps) { return <Glyph {...props}>↑</Glyph>; }
export function PlusIcon(props: IconProps) { return <Glyph {...props}>+</Glyph>; }
export function ReloadIcon(props: IconProps) { return <Glyph {...props}>↻</Glyph>; }
export function ArrowTopRightIcon(props: IconProps) { return <Glyph {...props}>↗</Glyph>; }

/** Preserve the chat mark already used by the cinema assistant. */
export function ChatBubbleIcon() {
  return <svg className="assistant-icon assistant-chat-mark" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-8l-6 3v-3a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" />
    <path d="M7 9h10M7 13h6" />
  </svg>;
}
