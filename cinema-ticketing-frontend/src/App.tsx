import { useEffect, useState, type FormEvent } from "react";

type Movie = {
  id: number;
  title: string;
  description?: string;
  duration?: number;
  genre?: string;
  director?: string;
  actors?: string;
  status?: string;
};

type ApiResponse<T> = {
  code: number;
  data: T;
};

const fallbackMovies: Movie[] = [
  {
    id: 1,
    title: "星际漫游",
    description: "一场穿越时间与记忆的深空旅程，在寂静宇宙中寻找人类留下的回声。",
    duration: 128,
    genre: "科幻 / 剧情",
    director: "林默",
    actors: "周野 / 许知意",
    status: "ON_SALE",
  },
  {
    id: 2,
    title: "午夜放映室",
    description: "旧影院重新亮灯后，一卷失落多年的胶片揭开了一段未完的故事。",
    duration: 104,
    genre: "悬疑 / 剧情",
    director: "沈北",
    actors: "陈默 / 夏禾",
    status: "ON_SALE",
  },
  {
    id: 3,
    title: "海岸线以南",
    description: "两个久别重逢的人，在一段沿海公路上重新理解告别的意义。",
    duration: 116,
    genre: "爱情 / 文艺",
    director: "苏禾",
    actors: "林川 / 顾南",
    status: "ON_SALE",
  },
];

async function loadMovies(): Promise<Movie[]> {
  const response = await fetch("/api/movies");
  if (!response.ok) {
    throw new Error("电影服务暂时不可用");
  }
  const payload = (await response.json()) as ApiResponse<Movie[]>;
  return payload.data ?? [];
}

function getMovieImage(movieId: number): string {
  const images = [
    "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=85",
  ];
  return images[(movieId - 1) % images.length];
}

function App() {
  const [movies, setMovies] = useState<Movie[]>(fallbackMovies);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [selectedMovie, setSelectedMovie] = useState<Movie | null>(null);
  const [isLoginOpen, setIsLoginOpen] = useState(false);
  const [loginName, setLoginName] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [bookingMessage, setBookingMessage] = useState("");

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setLoginMessage("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginName, password: loginPassword }),
      });
      const payload = (await response.json()) as ApiResponse<{ token: string; username: string }>;
      if (!response.ok || payload.code !== 0) {
        throw new Error((payload as ApiResponse<unknown> & { message?: string }).message ?? "登录失败，请检查账号信息");
      }
      localStorage.setItem("cinema-auth-token", payload.data.token);
      setLoginMessage(`欢迎回来，${payload.data.username}`);
      window.setTimeout(() => setIsLoginOpen(false), 700);
    } catch (error) {
      setLoginMessage(error instanceof Error ? error.message : "登录失败，请稍后再试");
    } finally {
      setIsSubmitting(false);
    }
  }

  useEffect(() => {
    loadMovies()
      .then((items) => {
        if (items.length > 0) {
          setMovies(items);
        }
      })
      .catch((error: Error) => setErrorMessage(error.message))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <main className="app-shell">
      <header className="site-header content-width">
        <a className="brand" href="#top" aria-label="Cinema 首页">
          <span className="brand-mark">C</span>
          <span>CINEMA</span>
        </a>
        <nav className="main-nav" aria-label="主导航">
          <a className="active" href="#movies">正在上映</a>
          <a href="#cinemas">影院</a>
          <a href="#orders">我的订单</a>
        </nav>
        <button className="account-button" type="button" onClick={() => setIsLoginOpen(true)}>登录 / 注册</button>
      </header>

      <section className="hero content-width" id="top">
        <div className="hero-copy">
          <p className="eyebrow">YOUR NEXT SCENE</p>
          <h1>今晚，<br /><em>走进</em> 一部好电影。</h1>
          <p className="hero-description">从选片到入场，把时间留给真正值得看的故事。</p>
          <a className="primary-button" href="#movies">查看正在上映</a>
        </div>
        <div className="hero-visual" role="img" aria-label="电影院放映厅的座椅">
          <div className="hero-visual-caption">
            <span>SCREEN 01</span>
            <span>NOW PLAYING</span>
          </div>
        </div>
      </section>

      <section className="movie-section content-width" id="movies">
        <div className="section-heading">
          <div>
            <p className="eyebrow">ON THE BIG SCREEN</p>
            <h2>正在上映</h2>
          </div>
          <p className="section-note">挑一部今晚想看的电影</p>
        </div>

        {isLoading && <div className="state-message">正在同步影院片单</div>}
        {errorMessage && <div className="state-message muted">{errorMessage}，已展示精选片单</div>}

        <div className="movie-grid">
          {movies.map((movie) => (
            <article className="movie-card" key={movie.id}>
              <div className="poster" style={{ backgroundImage: `url(${getMovieImage(movie.id)})` }}>
                <span className="poster-index">0{movie.id}</span>
                <span className="poster-duration">{movie.duration ?? "--"} MIN</span>
              </div>
              <div className="movie-info">
                <div>
                  <p className="movie-genre">{movie.genre ?? "FEATURE"}</p>
                  <h3>{movie.title}</h3>
                </div>
                <button type="button" onClick={() => setSelectedMovie(movie)}>查看详情 <span aria-hidden="true">↗</span></button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="service-strip content-width" id="cinemas">
        <div><span className="service-number">01</span><strong>先选电影</strong><span>按你的心情找到下一场放映</span></div>
        <div><span className="service-number">02</span><strong>再选座位</strong><span>实时查看每一个可用座位</span></div>
        <div><span className="service-number">03</span><strong>准时入场</strong><span>电子票随时在你的订单里</span></div>
      </section>

      <footer className="site-footer content-width">
        <span>CINEMA / 电影票务</span>
        <span>让每一次观影，都从选择开始。</span>
      </footer>

      {selectedMovie && (
        <div className="modal-backdrop" role="presentation" onClick={() => setSelectedMovie(null)}>
          <section className="movie-modal" role="dialog" aria-modal="true" aria-labelledby="movie-title" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" type="button" aria-label="关闭详情" onClick={() => setSelectedMovie(null)}>×</button>
            <p className="eyebrow">MOVIE DETAIL</p>
            <h2 id="movie-title">{selectedMovie.title}</h2>
            <p>{selectedMovie.description ?? "暂无简介"}</p>
            <dl>
              <div><dt>导演</dt><dd>{selectedMovie.director ?? "待公布"}</dd></div>
              <div><dt>主演</dt><dd>{selectedMovie.actors ?? "待公布"}</dd></div>
              <div><dt>类型</dt><dd>{selectedMovie.genre ?? "待公布"}</dd></div>
            </dl>
            <button className="primary-button" type="button" onClick={() => setBookingMessage("场次选择即将开放，请先登录后继续。")}>选择场次</button>
            {bookingMessage && <p className="modal-feedback">{bookingMessage}</p>}
          </section>
        </div>
      )}

      {isLoginOpen && (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsLoginOpen(false)}>
          <section className="login-modal" role="dialog" aria-modal="true" aria-labelledby="login-title" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" type="button" aria-label="关闭登录" onClick={() => setIsLoginOpen(false)}>×</button>
            <p className="eyebrow">WELCOME BACK</p>
            <h2 id="login-title">登录 CINEMA</h2>
            <form className="login-form" onSubmit={handleLogin}>
              <label>用户名<input value={loginName} onChange={(event) => setLoginName(event.target.value)} required /></label>
              <label>密码<input type="password" minLength={8} value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} required /></label>
              <button className="primary-button" type="submit" disabled={isSubmitting}>{isSubmitting ? "登录中" : "登录"}</button>
            </form>
            {loginMessage && <p className="modal-feedback">{loginMessage}</p>}
          </section>
        </div>
      )}
    </main>
  );
}

export { App };
