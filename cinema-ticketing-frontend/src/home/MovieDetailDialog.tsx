import { useEffect, useRef, useState, type ReactNode } from "react";
import MoviePoster from "./MoviePoster";

type Movie = { title: string; description?: string | null; director?: string | null; actors?: string | null; genre?: string | null; duration?: number | null; rating_average?: number | string | null; rating_count?: number };

export default function MovieDetailDialog({ movie, poster, fallback, saleWindow, salesLabel, onClose, onBook, children }: { movie: Movie; poster: string; fallback: string; saleWindow: string; salesLabel: string; onClose: () => void; onBook: () => void; children: ReactNode }) {
  const [tab, setTab] = useState<"info" | "reviews">("info");
  const dialog = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    close.current?.focus();
    return () => previous?.focus();
  }, []);
  return <div className="modal-backdrop" role="presentation" onClick={onClose}>
    <section ref={dialog} className="movie-modal movie-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="movie-title" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const targets = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], textarea, input, select, summary, [tabindex="0"]') ?? []).filter((element) => element.getClientRects().length > 0);
      const first = targets[0]; const last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}>
      <button ref={close} className="modal-close" type="button" aria-label="关闭详情" onClick={onClose}>×</button>
      <div className="detail-layout">
        <aside className="detail-art"><MoviePoster className="detail-poster" src={poster} fallback={fallback} alt={`《${movie.title}》海报`} /><p>在大银幕，遇见好故事。</p></aside>
        <div className="detail-content">
          <header><p className="eyebrow">MOVIE DETAIL / 影片详情</p><h2 id="movie-title">{movie.title}</h2><p className="detail-meta">{movie.genre || "电影"} · {movie.duration ?? "—"} 分钟 <span>{Number(movie.rating_count) > 0 ? `★ ${Number(movie.rating_average).toFixed(1)} / 5` : "暂无评分"}</span></p></header>
          <div className="detail-tabs" role="tablist" aria-label="影片详情内容" onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "Home" ? "info" : event.key === "End" ? "reviews" : tab === "info" ? "reviews" : "info";
            setTab(next);
            event.currentTarget.querySelector<HTMLButtonElement>(`#detail-${next}-tab`)?.focus();
          }}><button id="detail-info-tab" role="tab" tabIndex={tab === "info" ? 0 : -1} aria-selected={tab === "info"} aria-controls="detail-info-panel" type="button" onClick={() => setTab("info")}>影片信息</button><button id="detail-reviews-tab" role="tab" tabIndex={tab === "reviews" ? 0 : -1} aria-selected={tab === "reviews"} aria-controls="detail-reviews-panel" type="button" onClick={() => setTab("reviews")}>评论与评分{Number(movie.rating_count) > 0 ? ` · ${movie.rating_count}` : ""}</button></div>
          <div className="detail-panel" id="detail-info-panel" role="tabpanel" aria-labelledby="detail-info-tab" hidden={tab !== "info"}>
            <dl className="detail-facts"><div><dt>导演</dt><dd>{movie.director || "待公布"}</dd></div><div><dt>主演</dt><dd>{movie.actors || "待公布"}</dd></div><div><dt>上架周期</dt><dd>{saleWindow}</dd></div><div><dt>订购状态</dt><dd>{salesLabel}</dd></div></dl>
            <h3 className="detail-synopsis-heading">剧情简介</h3><p className="detail-synopsis">{movie.description || "暂无简介"}</p>
          </div>
          <div className="detail-panel" id="detail-reviews-panel" role="tabpanel" aria-labelledby="detail-reviews-tab" hidden={tab !== "reviews"}>{children}</div>
          <footer className="detail-actions"><button className="primary-button" type="button" onClick={onBook}>选择场次 <span aria-hidden="true">↗</span></button><span>挑选时间，再选择你的座位</span></footer>
        </div>
      </div>
    </section>
  </div>;
}
