import { useEffect, useRef, useState } from "react";
import MoviePoster from "./MoviePoster";

type Movie = { id: number; title: string; genre?: string | null; duration?: number | null; description?: string | null; rating_average?: number | string | null; rating_count?: number };
const SLIDE_DURATION = 650;

export default function MovieCarousel({ movies, poster, fallback, onSelect }: { movies: Movie[]; poster: (id: number) => string; fallback: (id: number) => string; onSelect: (id: number) => void }) {
  const [position, setPosition] = useState(1);
  const [paused, setPaused] = useState(false);
  const [transition, setTransition] = useState(true);
  const [cycle, setCycle] = useState(0);
  const moving = useRef(false);
  const pendingFrame = useRef(0);
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const count = movies.length;
  const movieIds = movies.map((movie) => movie.id).join(",");

  useEffect(() => {
    moving.current = false;
    setTransition(false);
    setPosition(1);
  }, [movieIds]);

  // End-slide copies keep the last-to-first transition moving forward.
  useEffect(() => {
    if (!transition) {
      const frame = window.requestAnimationFrame(() => {
        pendingFrame.current = window.requestAnimationFrame(() => { moving.current = false; setTransition(true); });
      });
      return () => { window.cancelAnimationFrame(frame); window.cancelAnimationFrame(pendingFrame.current); };
    }
    if (!moving.current) return;
    const timer = window.setTimeout(() => {
      if (position === 0 || position === count + 1) {
        setTransition(false);
        setPosition(position === 0 ? count : 1);
      } else moving.current = false;
    }, SLIDE_DURATION);
    return () => window.clearTimeout(timer);
  }, [position, count, transition]);

  useEffect(() => {
    if (paused || count < 2) return;
    const timer = window.setInterval(() => {
      if (document.hidden || moving.current) return;
      moving.current = true;
      setPosition((value) => value + 1);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [paused, count, cycle]);

  const moveTo = (next: number) => {
    if (moving.current || count < 2) return;
    moving.current = true;
    setPosition(next);
    setCycle((value) => value + 1);
  };
  const index = count ? (position - 1 + count) % count : 0;
  if (!count) return <section className="hero content-width"><div className="hero-copy"><p className="eyebrow">YOUR NEXT SCENE</p><h1>下一场，<br /><em>期待</em> 好故事。</h1><p className="hero-description">目前没有可售的上映影片，查看下方两周排期，寻找下一次观影。</p><a href="#schedule" className="primary-button">查看电影日程</a></div></section>;
  const slides = count > 1 ? [movies[count - 1], ...movies, movies[0]] : movies;
  const slidePosition = count > 1 ? position : 0;

  return <section className="feature-carousel" aria-label="正在上映电影轮播" aria-roledescription="轮播">
    <div className="feature-viewport" onTouchStart={(event) => { touchStart.current = { x: event.touches[0].clientX, y: event.touches[0].clientY }; }} onTouchEnd={(event) => {
      if (!touchStart.current) return;
      const dx = event.changedTouches[0].clientX - touchStart.current.x;
      const dy = event.changedTouches[0].clientY - touchStart.current.y;
      touchStart.current = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) moveTo(position + (dx < 0 ? 1 : -1));
    }} onTouchCancel={() => { touchStart.current = null; }}>
      <div className={`feature-track${transition ? " is-animated" : ""}`} style={{ transform: `translateX(calc(${-slidePosition * 100}% - ${slidePosition * 24}px))` }}>
        {slides.map((movie, slide) => <article className={`feature-slide${slide === slidePosition ? " is-current" : ""}`} key={`${slide}-${movie.id}`} aria-hidden={slide !== slidePosition} ref={(element) => { if (slide !== slidePosition) element?.setAttribute("inert", ""); else element?.removeAttribute("inert"); }} aria-roledescription="幻灯片" aria-label={`${index + 1} / ${count}：${movie.title}`}>
          <div className="feature-backdrop" style={{ backgroundImage: `url("${poster(movie.id)}"), url("${fallback(movie.id)}")` }} />
          <div className="feature-copy">
            <p className="eyebrow">NOW PLAYING / 正在上映</p><h1>{movie.title}</h1>
            <p className="feature-meta">{movie.genre || "电影"}<span> / </span>{movie.duration ?? "—"} 分钟</p>
            <p className="feature-rating">{Number(movie.rating_count) > 0 ? <>★ <strong>{Number(movie.rating_average).toFixed(1)}</strong><span> / 5 · {movie.rating_count} 人评分</span></> : <span>期待你的第一条观影评价</span>}</p>
            <p className="feature-description">{movie.description || "选一场电影，把时间留给值得看的故事。"}</p>
            <button className="primary-button" type="button" onClick={() => onSelect(movie.id)}>查看影片与场次 <span aria-hidden="true">↗</span></button>
          </div>
          <MoviePoster className="feature-poster" src={poster(movie.id)} fallback={fallback(movie.id)} alt={`${movie.title}电影海报`} />
        </article>)}
      </div>
    </div>
    {count > 1 && <><button className="feature-arrow previous" type="button" aria-label="上一部电影" onClick={() => moveTo(position - 1)}><span aria-hidden="true">‹</span></button><button className="feature-arrow next" type="button" aria-label="下一部电影" onClick={() => moveTo(position + 1)}><span aria-hidden="true">›</span></button></>}
    <div className="feature-navigation">
      <span className="feature-counter">{String(index + 1).padStart(2, "0")} <span>/ {String(count).padStart(2, "0")}</span></span>
      <div className="feature-dots" aria-label="选择轮播影片">{movies.map((movie, dot) => <button key={movie.id} type="button" aria-label={`切换到${movie.title}`} aria-current={dot === index ? "true" : undefined} onClick={() => { if (dot !== index) moveTo(dot + 1); }} />)}</div>
      {count > 1 && <button className="feature-pause" type="button" aria-pressed={paused} onClick={() => setPaused((value) => !value)}>{paused ? "▶ 自动播放" : "Ⅱ 暂停轮播"}</button>}
    </div>
  </section>;
}
