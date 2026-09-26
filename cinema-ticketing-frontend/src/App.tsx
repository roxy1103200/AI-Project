import { useEffect, useState, type FormEvent } from "react";
import MovieAdmin from "./admin/MovieAdmin";
import CinemaAdmin from "./admin/CinemaAdmin";
import RefundControl from "./orders/RefundControl";
import TicketDialog from "./orders/TicketDialog";
import MovieCarousel from "./home/MovieCarousel";
import TwoWeekSchedule from "./home/TwoWeekSchedule";
import MovieReviews from "./home/MovieReviews";
import MovieDetailDialog from "./home/MovieDetailDialog";

type Movie = {
  id: number;
  title: string;
  description?: string | null;
  duration?: number | null;
  release_date?: string | null;
  sale_start_time?: string | null;
  sale_end_time?: string | null;
  sales_status?: string;
  future_screening_count?: number;
  rating_average?: number | string | null;
  rating_count?: number;
  genre?: string | null;
  director?: string | null;
  actors?: string | null;
  status?: string | null;
};

type Screening = {
  id: number;
  movie_id: number;
  hall_id: number;
  start_time: string;
  end_time: string;
  price: number | string;
  status: string;
};

type Cinema = { id: number; name: string; address: string; phone?: string | null; status?: string | null };
type Hall = { id: number; cinema_id: number; name: string; hall_type?: string; status?: string };
type Seat = {
  id: number;
  row_no: number;
  column_no: number;
  seat_code: string;
  seat_type?: string;
  status: string;
  booking_status?: string;
};

type OrderSummary = {
  order_no: string;
  screening_id: number;
  movie_title?: string;
  start_time?: string;
  hall_name?: string;
  cinema_name?: string;
  refund_deadline?: string | null;
  can_refund?: boolean;
  refund_reason?: string;
  server_time?: string;
  received_at?: number;
  total_amount: number | string;
  status: string;
  expire_at?: string;
  paid_at?: string;
  created_at?: string;
};

type OrderItem = {
  seat_id: number;
  seat_code: string;
  price: number | string;
  ticket_status: string;
};

type OrderView = {
  orderNo: string;
  userId: number;
  screeningId: number;
  totalAmount: number | string;
  status: string;
  expireAt?: string;
  paidAt?: string;
  startTime: string;
  items: OrderItem[];
};

type ApiResponse<T> = { code: number; message?: string; data: T };
type AuthMode = "login" | "register";
type BookingStep = "screenings" | "seats";

type LoginPayload = {
  token: string;
  userId: number;
  username: string;
  role: string;
  expiresInSeconds: number;
};

type StoredSession = LoginPayload & { expiresAt: number };

const AUTH_STORAGE_KEY = "cinema-auth";
const LEGACY_TOKEN_KEY = "cinema-auth-token";
const MAX_SEATS_PER_ORDER = 6;

function movieSalesLabel(movie: Movie): string {
  const now = Date.now();
  if (movie.status === "OFFLINE") return "已下线";
  if (movie.sales_status === "NOT_STARTED" || (movie.sale_start_time && new Date(`${movie.sale_start_time}+08:00`).getTime() > now)) return Number(movie.future_screening_count) > 0 ? "已排期，待上架" : "待上架";
  if (movie.sale_end_time && new Date(`${movie.sale_end_time}+08:00`).getTime() <= now) return "上架已截止";
  if (movie.sales_status === "AVAILABLE") return "可订购";
  if (movie.sales_status === "NO_SCREENINGS") return "待排期";
  return movie.status === "UPCOMING" ? "即将上映" : "正在上映";
}

async function apiRequest<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("X-Auth-Token", token);
  }

  const response = await fetch(path, { ...init, headers });
  const payload = await response.json().catch(() => null) as ApiResponse<T> | null;
  if (!payload) {
    throw new Error("服务暂时无法响应，请稍后重试");
  }
  if (!response.ok || payload.code !== 0) {
    throw new Error(payload.message ?? `请求失败（${response.status}）`);
  }
  return payload.data;
}

function readSession(): StoredSession | null {
  localStorage.removeItem(LEGACY_TOKEN_KEY);
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredSession;
    if (!parsed.token || !parsed.expiresAt || parsed.expiresAt <= Date.now()) {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    localStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

function saveSession(payload: LoginPayload): StoredSession {
  const stored: StoredSession = { ...payload, expiresAt: Date.now() + payload.expiresInSeconds * 1000 };
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(stored));
  return stored;
}

function formatDateTime(value?: string): string {
  if (!value) return "时间待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.replace("T", " ").slice(0, 16);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function amount(value: number | string): string {
  return Number(value).toFixed(2);
}

function orderStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    UNPAID: "待支付", PAID: "支付处理中", ISSUED: "已出票", REFUNDED: "已退票", CANCELLED: "已取消",
  };
  return labels[status] ?? status;
}

function getMovieImage(movieId: number): string {
  const images = [
    "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=1200&q=85",
    "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=85",
  ];
  return images[(Math.max(movieId, 1) - 1) % images.length];
}

function moviePosterBackground(movieId: number, version: number): string {
  return `url("${moviePosterUrl(movieId, version)}"), url("${getMovieImage(movieId)}")`;
}

function moviePosterUrl(movieId: number, version: number): string {
  return `/api/movies/${movieId}/poster?v=${version}`;
}

function App() {
  const [movies, setMovies] = useState<Movie[]>([]);
  const [screenings, setScreenings] = useState<Screening[]>([]);
  const [isScreeningsLoading, setIsScreeningsLoading] = useState(false);
  const [screeningsError, setScreeningsError] = useState("");
  const [cinemas, setCinemas] = useState<Cinema[]>([]);
  const [isCinemaLoading, setIsCinemaLoading] = useState(true);
  const [cinemaError, setCinemaError] = useState("");
  const [imageVersion, setImageVersion] = useState(0);
  const [halls, setHalls] = useState<Hall[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [selectedMovie, setSelectedMovie] = useState<Movie | null>(null);
  const [session, setSession] = useState<StoredSession | null>(() => readSession());
  const [activeView, setActiveView] = useState<"catalog" | "movies" | "cinemas">("catalog");
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [loginName, setLoginName] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [authFailed, setAuthFailed] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isBookingOpen, setIsBookingOpen] = useState(false);
  const [bookingMovie, setBookingMovie] = useState<Movie | null>(null);
  const [bookingStep, setBookingStep] = useState<BookingStep>("screenings");
  const [selectedScreening, setSelectedScreening] = useState<Screening | null>(null);
  const [seats, setSeats] = useState<Seat[]>([]);
  const [selectedSeatIds, setSelectedSeatIds] = useState<number[]>([]);
  const [activeOrder, setActiveOrder] = useState<OrderView | null>(null);
  const [bookingMessage, setBookingMessage] = useState("");
  const [bookingFailed, setBookingFailed] = useState(false);
  const [isBookingAction, setIsBookingAction] = useState(false);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [orderDetails, setOrderDetails] = useState<Record<string, OrderView>>({});
  const [expandedOrder, setExpandedOrder] = useState<string | null>(null);
  const [ordersMessage, setOrdersMessage] = useState("");
  const [isOrdersLoading, setIsOrdersLoading] = useState(false);
  const [activeOrderAction, setActiveOrderAction] = useState<string | null>(null);
  const [movieCategory, setMovieCategory] = useState("showing");
  const [ticketOrderNo, setTicketOrderNo] = useState<string | null>(null);

  const movieById = new Map(movies.map((movie) => [movie.id, movie]));
  const publicMovies = movies.filter((movie) => movie.status !== "OFFLINE");
  function movieGroup(movie: Movie): string {
    const label = movieSalesLabel(movie);
    if (label === "上架已截止") return "ended";
    if (movie.sales_status === "NOT_STARTED" || label === "待上架" || label === "已排期，待上架" || movie.status === "UPCOMING") return "upcoming";
    return label === "待排期" ? "pending" : "showing";
  }
  const movieCategories = [
    { id: "showing", label: "正在上映" }, { id: "pending", label: "待排期" },
    { id: "upcoming", label: "即将上映" }, { id: "ended", label: "已截止" },
  ];
  const displayedMovies = publicMovies.filter((movie) => movieGroup(movie) === movieCategory);
  const hallById = new Map(halls.map((hall) => [hall.id, hall]));
  const cinemaById = new Map(cinemas.map((cinema) => [cinema.id, cinema]));

  function openAuth(mode: AuthMode) {
    setAuthMode(mode);
    setAuthMessage("");
    setAuthFailed(false);
    setLoginPassword("");
    setConfirmPassword("");
    setIsAuthOpen(true);
  }

  function switchAuthMode(mode: AuthMode) {
    setAuthMode(mode);
    setAuthMessage("");
    setAuthFailed(false);
    setLoginPassword("");
    setConfirmPassword("");
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setAuthMessage("");
    try {
      const payload = await apiRequest<LoginPayload>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: loginName, password: loginPassword }),
      });
      setSession(saveSession(payload));
      setAuthFailed(false);
      setAuthMessage(`欢迎回来，${payload.username}`);
      window.setTimeout(() => setIsAuthOpen(false), 500);
    } catch (error) {
      setAuthFailed(true);
      setAuthMessage(error instanceof Error ? error.message : "登录失败，请稍后再试");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loginPassword !== confirmPassword) {
      setAuthFailed(true);
      setAuthMessage("两次输入的密码不一致");
      return;
    }
    setIsSubmitting(true);
    setAuthMessage("");
    try {
      const account = await apiRequest<{ id: number; username: string }>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ username: loginName, password: loginPassword, phone: phone || null }),
      });
      setAuthMode("login");
      setLoginPassword("");
      setConfirmPassword("");
      setAuthFailed(false);
      setAuthMessage(`账号 ${account.username} 注册成功，请登录`);
    } catch (error) {
      setAuthFailed(true);
      setAuthMessage(error instanceof Error ? error.message : "注册失败，请稍后再试");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLogout() {
    const token = session?.token;
    localStorage.removeItem(AUTH_STORAGE_KEY);
    setSession(null);
    setActiveView("catalog");
    setOrders([]);
    setOrderDetails({});
    if (!token) return;
    try {
      await apiRequest<void>("/api/auth/logout", { method: "POST" }, token);
    } catch {
      // 本地已退出；即使服务端请求未送达，会话也会在两小时后过期。
    }
  }

  async function refreshOrders(token = session?.token) {
    if (!token) {
      setOrders([]);
      return;
    }
    setIsOrdersLoading(true);
    setOrdersMessage("");
    try {
      const result = await apiRequest<OrderSummary[]>("/api/orders", {}, token);
      setOrders((result ?? []).map((order) => ({ ...order, received_at: Date.now() })));
    } catch (error) {
      setOrdersMessage(error instanceof Error ? error.message : "订单读取失败");
    } finally {
      setIsOrdersLoading(false);
    }
  }

  async function refreshMovies(refreshPoster = true) {
    const [result, slots] = await Promise.all([apiRequest<Movie[]>("/api/movies"), apiRequest<Screening[]>("/api/screenings")]);
    setMovies(result ?? []);
    setScreenings(slots ?? []);
    setErrorMessage("");
    if (refreshPoster) setImageVersion((current) => current + 1);
  }

  async function refreshCinemas() {
    setIsCinemaLoading(true);
    try {
      const result = await apiRequest<Cinema[]>("/api/cinemas");
      setCinemas(result ?? []);
      setCinemaError("");
    } catch (error) {
      setCinemaError(error instanceof Error ? error.message : "影院读取失败");
      throw error;
    } finally {
      setIsCinemaLoading(false);
    }
  }

  useEffect(() => {
    if (activeView !== "catalog") return;
    const refresh = () => { if (!document.hidden) void refreshMovies(false).catch(() => {}); };
    refresh();
    const timer = window.setInterval(refresh, 60000);
    window.addEventListener("focus", refresh);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [activeView]);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      const [movieResult, screeningResult, cinemaResult, hallResult] = await Promise.allSettled([
        apiRequest<Movie[]>("/api/movies"),
        apiRequest<Screening[]>("/api/screenings"),
        apiRequest<Cinema[]>("/api/cinemas"),
        apiRequest<Hall[]>("/api/halls"),
      ]);
      if (!mounted) return;
      if (movieResult.status === "fulfilled") setMovies(movieResult.value ?? []);
      else setErrorMessage(movieResult.reason instanceof Error ? movieResult.reason.message : "电影服务暂时不可用");
      if (screeningResult.status === "fulfilled") setScreenings(screeningResult.value ?? []);
      if (cinemaResult.status === "fulfilled") setCinemas(cinemaResult.value ?? []);
      else setCinemaError(cinemaResult.reason instanceof Error ? cinemaResult.reason.message : "影院服务暂时不可用");
      setIsCinemaLoading(false);
      if (hallResult.status === "fulfilled") setHalls(hallResult.value ?? []);
      setIsLoading(false);
    };
    void load();
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    setTicketOrderNo(null);
    void refreshOrders();
    const timer = window.setInterval(() => { if (session?.token) void refreshOrders(session.token); }, 30000);
    // Session changes only when logging in or out; refreshOrders is intentionally not an effect dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => window.clearInterval(timer);
  }, [session?.token]);

  useEffect(() => {
    if (!isBookingOpen || !bookingMovie) return;
    let mounted = true;
    setIsScreeningsLoading(true);
    setScreeningsError("");
    apiRequest<Screening[]>("/api/screenings")
      .then((result) => { if (mounted) setScreenings(result ?? []); })
      .catch((error: unknown) => {
        if (mounted) setScreeningsError(error instanceof Error ? error.message : "场次读取失败，请重新打开重试。");
      })
      .finally(() => { if (mounted) setIsScreeningsLoading(false); });
    return () => { mounted = false; };
  }, [isBookingOpen, bookingMovie]);

  function openBooking(movie: Movie) {
    setSelectedMovie(null);
    setBookingMovie(movie);
    setBookingStep("screenings");
    setSelectedScreening(null);
    setSeats([]);
    setSelectedSeatIds([]);
    setActiveOrder(null);
    setBookingMessage("");
    setBookingFailed(false);
    setIsScreeningsLoading(true);
    setScreeningsError("");
    setIsBookingOpen(true);
  }

  async function chooseScreening(screening: Screening) {
    setIsBookingAction(true);
    setBookingMessage("");
    setBookingFailed(false);
    try {
      const result = await apiRequest<Seat[]>(`/api/screenings/${screening.id}/seats`);
      setSelectedScreening(screening);
      setSeats(result ?? []);
      setSelectedSeatIds([]);
      setBookingStep("seats");
    } catch (error) {
      setBookingFailed(true);
      setBookingMessage(error instanceof Error ? error.message : "座位读取失败");
    } finally {
      setIsBookingAction(false);
    }
  }

  async function reloadSeats(silent = false) {
    if (!selectedScreening) return;
    if (!silent) setIsBookingAction(true);
    try {
      const result = await apiRequest<Seat[]>(`/api/screenings/${selectedScreening.id}/seats`);
      setSeats(result ?? []);
      setSelectedSeatIds((current) => current.filter((id) => result.some((seat) => seat.id === id && (seat.booking_status ?? seat.status) === "AVAILABLE")));
      if (!silent) {
        setBookingMessage("座位状态已更新");
        setBookingFailed(false);
      }
    } catch (error) {
      if (!silent) {
        setBookingFailed(true);
        setBookingMessage(error instanceof Error ? error.message : "座位刷新失败");
      }
    } finally {
      if (!silent) setIsBookingAction(false);
    }
  }

  function toggleSeat(seat: Seat) {
    const status = seat.booking_status ?? seat.status;
    if (status !== "AVAILABLE") return;
    setSelectedSeatIds((current) => {
      if (current.includes(seat.id)) return current.filter((id) => id !== seat.id);
      if (current.length >= MAX_SEATS_PER_ORDER) {
        setBookingFailed(true);
        setBookingMessage(`每笔订单最多选择 ${MAX_SEATS_PER_ORDER} 个座位`);
        return current;
      }
      setBookingMessage("");
      setBookingFailed(false);
      return [...current, seat.id];
    });
  }

  async function createOrder() {
    if (!session) {
      setBookingMessage("请先登录后再锁座下单");
      setBookingFailed(true);
      openAuth("login");
      return;
    }
    if (!selectedScreening || selectedSeatIds.length === 0) {
      setBookingMessage("请先选择场次和座位");
      setBookingFailed(true);
      return;
    }
    setIsBookingAction(true);
    setBookingMessage("");
    setBookingFailed(false);
    try {
      await apiRequest<{ screeningId: number; seatIds: number[]; lockedUntil: string }>("/api/orders/lock-seats", {
        method: "POST",
        body: JSON.stringify({ screeningId: selectedScreening.id, seatIds: selectedSeatIds }),
      }, session.token);
      const requestId = typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const order = await apiRequest<OrderView>("/api/orders", {
        method: "POST",
        body: JSON.stringify({ screeningId: selectedScreening.id, seatIds: selectedSeatIds, requestId }),
      }, session.token);
      setActiveOrder(order);
      setOrderDetails((current) => ({ ...current, [order.orderNo]: order }));
      await refreshOrders(session.token);
    } catch (error) {
      setBookingFailed(true);
      setBookingMessage(error instanceof Error ? error.message : "下单失败，请刷新座位后重试");
      await reloadSeats(true);
    } finally {
      setIsBookingAction(false);
    }
  }

  async function payActiveOrder() {
    if (!session || !activeOrder) return;
    setIsBookingAction(true);
    setBookingMessage("");
    try {
      const result = await apiRequest<OrderView>(`/api/orders/${activeOrder.orderNo}/pay`, {
        method: "POST",
        // 当前工程没有接入真实支付渠道；使用固定演示流水号确保重复提交具备幂等性。
        body: JSON.stringify({ paymentNo: `DEMO-${activeOrder.orderNo}` }),
      }, session.token);
      setActiveOrder(result);
      setOrderDetails((current) => ({ ...current, [result.orderNo]: result }));
      setBookingMessage("支付成功，电子票已出票");
      setBookingFailed(false);
      await refreshOrders(session.token);
    } catch (error) {
      setBookingFailed(true);
      setBookingMessage(error instanceof Error ? error.message : "支付未完成，请重试");
    } finally {
      setIsBookingAction(false);
    }
  }

  async function cancelActiveOrder() {
    if (!session || !activeOrder) return;
    setIsBookingAction(true);
    try {
      const result = await apiRequest<OrderView>(`/api/orders/${activeOrder.orderNo}/cancel`, { method: "POST" }, session.token);
      setActiveOrder(result);
      setOrderDetails((current) => ({ ...current, [result.orderNo]: result }));
      setBookingMessage("订单已取消，座位已释放");
      setBookingFailed(false);
      await refreshOrders(session.token);
    } catch (error) {
      setBookingFailed(true);
      setBookingMessage(error instanceof Error ? error.message : "取消失败，请刷新订单状态");
    } finally {
      setIsBookingAction(false);
    }
  }

  async function toggleOrderDetails(orderNo: string) {
    if (expandedOrder === orderNo) {
      setExpandedOrder(null);
      return;
    }
    setExpandedOrder(orderNo);
    if (orderDetails[orderNo] || !session) return;
    try {
      const detail = await apiRequest<OrderView>(`/api/orders/${orderNo}`, {}, session.token);
      setOrderDetails((current) => ({ ...current, [orderNo]: detail }));
    } catch (error) {
      setOrdersMessage(error instanceof Error ? error.message : "订单详情读取失败");
    }
  }

  async function runOrderAction(orderNo: string, action: "cancel" | "refund" | "pay") {
    if (!session) return;
    setActiveOrderAction(orderNo);
    setOrdersMessage("");
    try {
      const path = `/api/orders/${orderNo}/${action}`;
      const init: RequestInit = action === "cancel"
        ? { method: "POST" }
        : { method: "POST", body: JSON.stringify(action === "pay"
          ? { paymentNo: `DEMO-${orderNo}` } : { reason: "用户申请退票" }) };
      const detail = await apiRequest<OrderView>(path, init, session.token);
      setOrderDetails((current) => ({ ...current, [orderNo]: detail }));
      setActiveOrder((current) => current?.orderNo === orderNo ? detail : current);
      await refreshOrders(session.token);
      setOrdersMessage(action === "cancel" ? "待支付订单已取消，座位已释放"
        : action === "pay" ? "支付成功，电子票已出票" : "退票已完成");
    } catch (error) {
      setOrdersMessage(error instanceof Error ? error.message : "操作失败，请刷新后重试");
    } finally {
      setActiveOrderAction(null);
    }
  }

  const availableScreenings = bookingMovie
    ? screenings.filter((screening) => screening.movie_id === bookingMovie.id
      && screening.status === "SCHEDULED" && new Date(screening.start_time).getTime() > Date.now()
      && hallById.get(screening.hall_id)?.status === "ACTIVE"
      && cinemaById.get(hallById.get(screening.hall_id)?.cinema_id ?? -1)?.status === "ACTIVE")
      .sort((left, right) => left.start_time.localeCompare(right.start_time))
    : [];
  const maxColumn = Math.max(0, ...seats.map((seat) => seat.column_no));
  const seatRows = [...new Set(seats.map((seat) => seat.row_no))].sort((a, b) => a - b);

  function screeningVenue(screening: Screening): string {
    const hall = hallById.get(screening.hall_id);
    const cinema = hall ? cinemaById.get(hall.cinema_id) : undefined;
    return [cinema?.name, hall?.name].filter(Boolean).join(" · ") || "影院信息待更新";
  }

  return (
    <main className="app-shell">
      <header className="site-header content-width">
        <a className="brand" href="#top" aria-label="Cinema 首页" onClick={() => setActiveView("catalog")}>
          <span className="brand-mark">C</span><span>CINEMA</span>
        </a>
        <nav className="main-nav" aria-label="主导航">
          <a className={activeView === "catalog" ? "active" : ""} href="#movies" onClick={() => { setMovieCategory("showing"); setActiveView("catalog"); }}>正在上映</a>
          <a href="#cinemas" onClick={() => setActiveView("catalog")}>影院</a>
          <a href="#orders" onClick={() => setActiveView("catalog")}>我的订单</a>
          {session?.role === "ADMIN" && <button className={`main-nav-control ${activeView === "movies" ? "active" : ""}`} type="button" onClick={() => { setSelectedMovie(null); setActiveView("movies"); }}>影片管理</button>}
          {session?.role === "ADMIN" && <button className={`main-nav-control ${activeView === "cinemas" ? "active" : ""}`} type="button" onClick={() => { setSelectedMovie(null); setActiveView("cinemas"); }}>影院管理</button>}
        </nav>
        {session ? (
          <div className={`account-area ${session.role === "ADMIN" ? "admin-account" : ""}`}>
            {session.role === "ADMIN" && <><button className="admin-mobile-shortcut" type="button" onClick={() => { setSelectedMovie(null); setActiveView("movies"); }}>影片</button><button className="admin-mobile-shortcut" type="button" onClick={() => { setSelectedMovie(null); setActiveView("cinemas"); }}>影院</button></>}
            <span className="account-name" title={`已登录：${session.username}（${session.role}）`}>
              <span className="account-dot" aria-hidden="true" />{session.username}
            </span>
            <button className="account-button" type="button" onClick={handleLogout}>退出登录</button>
          </div>
        ) : (
          <button className="account-button" type="button" onClick={() => openAuth("login")}>登录 / 注册</button>
        )}
      </header>

      {session?.role === "ADMIN" && activeView === "movies" ? (
        <MovieAdmin movies={movies} isLoading={isLoading} errorMessage={errorMessage} imageVersion={imageVersion} token={session.token} request={apiRequest} onRefresh={refreshMovies} />
      ) : session?.role === "ADMIN" && activeView === "cinemas" ? (
        <CinemaAdmin cinemas={cinemas} halls={halls} isLoading={isCinemaLoading} errorMessage={cinemaError} token={session.token} request={apiRequest} onRefresh={refreshCinemas} />
      ) : (
      <>
      <div id="top"><MovieCarousel movies={publicMovies.filter((movie) => movieGroup(movie) === "showing" && movie.sales_status === "AVAILABLE")} poster={(id) => moviePosterUrl(id, imageVersion)} fallback={getMovieImage} onSelect={(id) => setSelectedMovie(movieById.get(id) ?? null)} /></div>

      <section className="movie-section content-width" id="movies">
        <div className="section-heading">
          <div><p className="eyebrow">ON THE BIG SCREEN</p><h2>{movieCategories.find((category) => category.id === movieCategory)?.label}</h2></div>
          <p className="section-note">挑一部今晚想看的电影</p>
        </div>
        <div className="movie-category-tabs" role="group" aria-label="影片分类">{movieCategories.map((category) => <button key={category.id} type="button" aria-pressed={movieCategory === category.id} className={movieCategory === category.id ? "active" : ""} onClick={() => setMovieCategory(category.id)}>{category.label}<span>{publicMovies.filter((movie) => movieGroup(movie) === category.id).length}</span></button>)}</div>
        {movieCategory === "pending" && <p className="section-note">这些影片尚无可售场次，影院完成排期后会进入可订购片单。</p>}
        {isLoading && <div className="state-message">正在同步影院片单</div>}
        {errorMessage && <div className="state-message muted">{errorMessage}</div>}
        {!isLoading && displayedMovies.length === 0 && <div className="empty-state">当前分类暂无影片。</div>}
        <div className="movie-grid">
          {displayedMovies.map((movie) => (
            <article className="movie-card" key={movie.id}>
              <div className="poster" style={{ backgroundImage: moviePosterBackground(movie.id, imageVersion) }}>
                <span className="poster-index">{String(movie.id).padStart(2, "0")}</span>
                <span className="poster-duration">{movie.duration ?? "--"} MIN</span>
                <span className="poster-sales-status">{movieSalesLabel(movie)}</span>
              </div>
              <div className="movie-info">
                <div><p className="movie-genre">{movie.genre ?? "FEATURE"}</p><h3>{movie.title}</h3><p className="movie-rating">{Number(movie.rating_count) > 0 ? "★ " + Number(movie.rating_average).toFixed(1) + " / 5 · " + movie.rating_count + " 条评价" : "暂无评分"}</p></div>
                <button type="button" onClick={() => setSelectedMovie(movie)}>查看详情 <span aria-hidden="true">↗</span></button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <TwoWeekSchedule movies={movies} halls={halls} cinemas={cinemas} request={apiRequest} onSelect={(screening) => { const movie = movieById.get(screening.movie_id); if (movie) { openBooking(movie); void chooseScreening(screening); } }} />

      <section className="cinema-section content-width" id="cinemas">
        <div className="section-heading">
          <div><p className="eyebrow">NEAR YOUR NEXT SCENE</p><h2>选择影院</h2></div>
          <button className="text-button" type="button" disabled={isCinemaLoading} onClick={() => { void refreshCinemas().catch(() => {}); }}>刷新影院 ↻</button>
        </div>
        {isCinemaLoading && <div className="state-message">正在读取影院信息</div>}
        {cinemaError && <div className="state-message muted">{cinemaError}</div>}
        {!isCinemaLoading && !cinemaError && !cinemas.some((cinema) => cinema.status === "ACTIVE") && <div className="empty-state">暂时没有营业中的影院。</div>}
        <div className="cinema-grid">
          {cinemas.filter((cinema) => cinema.status === "ACTIVE").map((cinema) => (
            <article className="cinema-card" key={cinema.id}>
              <span className="cinema-open">正常营业 · {halls.filter((hall) => hall.cinema_id === cinema.id && hall.status === "ACTIVE").length} 个开放影厅</span>
              <h3>{cinema.name}</h3>
              <p>{cinema.address}</p>
              {cinema.phone && <p>联系电话：{cinema.phone}</p>}
            </article>
          ))}
        </div>
      </section>

      <section className="service-strip content-width">
        <div><span className="service-number">01</span><strong>先选电影</strong><span>按你的心情找到下一场放映</span></div>
        <div><span className="service-number">02</span><strong>再选座位</strong><span>实时查看每一个可用座位</span></div>
        <div><span className="service-number">03</span><strong>准时入场</strong><span>电子票随时在你的订单里</span></div>
      </section>

      <section className="orders-section content-width" id="orders">
        <div className="section-heading">
          <div><p className="eyebrow">YOUR TICKETS</p><h2>我的订单</h2></div>
          {session && <button className="text-button" type="button" onClick={() => void refreshOrders()}>刷新订单 ↻</button>}
        </div>
        {!session ? (
          <div className="empty-state order-login"><span>登录后查看你的购票记录与电子票。</span><button className="primary-button" type="button" onClick={() => openAuth("login")}>登录查看</button></div>
        ) : (
          <>
            {isOrdersLoading && <div className="state-message">正在读取订单</div>}
            {ordersMessage && <p className="order-feedback">{ordersMessage}</p>}
            {!isOrdersLoading && orders.length === 0 && <div className="empty-state">还没有订单，选一场电影开始吧。</div>}
            <div className="order-list">
              {orders.map((order) => {
                const screening = screenings.find((item) => item.id === order.screening_id);
                const movie = screening ? movieById.get(screening.movie_id) : undefined;
                const detail = orderDetails[order.order_no];
                return (
                  <article className="order-card" key={order.order_no}>
                    <div className="order-card-main">
                      <div className="order-card-title">
                        <span className={`order-status status-${order.status.toLowerCase()}`}>{orderStatusLabel(order.status)}</span>
                        <h3>{order.movie_title ?? movie?.title ?? `场次 ${order.screening_id}`}</h3>
                        <p>{order.start_time
                          ? `${formatDateTime(order.start_time)} · ${order.cinema_name ?? ""} · ${order.hall_name ?? ""}`
                          : screening ? `${formatDateTime(screening.start_time)} · ${screeningVenue(screening)}` : "场次信息"}</p>
                      </div>
                      <div className="order-card-side">
                        <strong>¥{amount(order.total_amount)}</strong>
                        <span>订单号 {order.order_no}</span>
                        <button className="order-ticket-button" type="button" onClick={() => setTicketOrderNo(order.order_no)}>{order.status === "ISSUED" ? "查看电影票" : "查看座位"}</button>
                      </div>
                    </div>
                    {expandedOrder === order.order_no && (
                      <div className="order-card-detail">
                        <div className="order-seat-list">
                          {detail?.items?.length
                            ? detail.items.map((item) => <span key={item.seat_id}>{item.seat_code}</span>)
                            : <span>{detail ? "暂无座位明细" : "正在读取座位明细…"}</span>}
                        </div>
                        <div className="order-card-actions">
                          {order.status === "UNPAID" && <button type="button" disabled={activeOrderAction !== null} onClick={() => void runOrderAction(order.order_no, "pay")}>继续支付</button>}
                          {order.status === "UNPAID" && <button type="button" disabled={activeOrderAction === order.order_no} onClick={() => void runOrderAction(order.order_no, "cancel")}>取消订单</button>}
                          {order.status === "ISSUED" && <RefundControl deadline={order.refund_deadline} canRefund={order.can_refund} reason={order.refund_reason} serverTime={order.server_time} receivedAt={order.received_at} busy={activeOrderAction !== null} onRefund={() => void runOrderAction(order.order_no, "refund")} />}
                          {activeOrderAction === order.order_no && <span>处理中…</span>}
                        </div>
                      </div>
                    )}
                    <button className="order-expand" type="button" onClick={() => void toggleOrderDetails(order.order_no)}>
                      {expandedOrder === order.order_no ? "收起订单详情 ↑" : "查看订单详情 ↓"}
                    </button>
                  </article>
                );
              })}
            </div>
          </>
        )}
      </section>

      <footer className="site-footer content-width">
        <span>CINEMA / 电影票务</span><span>让每一次观影，都从选择开始。</span>
      </footer>
      </>
      )}

      {activeView === "catalog" && selectedMovie && (
        <MovieDetailDialog key={selectedMovie.id} movie={selectedMovie} poster={moviePosterUrl(selectedMovie.id, imageVersion)} fallback={getMovieImage(selectedMovie.id)}
          saleWindow={selectedMovie.sale_start_time && selectedMovie.sale_end_time ? `${formatDateTime(selectedMovie.sale_start_time)} 至 ${formatDateTime(selectedMovie.sale_end_time)}` : "未设置时间限制"}
          salesLabel={`${movieSalesLabel(selectedMovie)}${selectedMovie.sales_status === "NO_SCREENINGS" ? "，影院安排场次后可订购" : ""}`}
          onClose={() => setSelectedMovie(null)} onBook={() => openBooking(selectedMovie)}>
          <MovieReviews movieId={selectedMovie.id} token={session?.token} request={apiRequest} onLogin={() => openAuth("login")} onChanged={refreshMovies} />
        </MovieDetailDialog>
      )}

      {isBookingOpen && bookingMovie && (
        <div className="modal-backdrop booking-backdrop" role="presentation" onClick={() => setIsBookingOpen(false)}>
          <section className="booking-modal" role="dialog" aria-modal="true" aria-labelledby="booking-title" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" type="button" aria-label="关闭购票" onClick={() => setIsBookingOpen(false)}>×</button>
            <p className="eyebrow">BOOK YOUR SEAT</p>
            <h2 id="booking-title">{bookingMovie.title}</h2>
            {activeOrder ? (
              <div className="checkout-panel">
                <div className="checkout-status"><span className={`order-status status-${activeOrder.status.toLowerCase()}`}>{orderStatusLabel(activeOrder.status)}</span><span>订单号 {activeOrder.orderNo}</span></div>
                <div className="checkout-summary">
                  <span>{activeOrder.items.map((item) => item.seat_code).join("、") || `${activeOrder.items.length} 个座位`}</span>
                  <strong>¥{amount(activeOrder.totalAmount)}</strong>
                </div>
                {activeOrder.expireAt && activeOrder.status === "UNPAID" && <p className="checkout-hint">请在 {formatDateTime(activeOrder.expireAt)} 前完成支付，超时订单会自动取消。</p>}
                {activeOrder.status === "UNPAID" && (
                  <div className="checkout-actions">
                    <button className="primary-button" type="button" disabled={isBookingAction} onClick={() => void payActiveOrder()}>{isBookingAction ? "处理中…" : "模拟支付并出票"}</button>
                    <button className="secondary-button" type="button" disabled={isBookingAction} onClick={() => void cancelActiveOrder()}>取消订单</button>
                  </div>
                )}
                {activeOrder.status === "ISSUED" && <p className="ticket-success">支付成功，订单已出票。你可以在「我的订单」查看电子票。</p>}
                {activeOrder.status === "CANCELLED" && <p className="checkout-hint">订单已取消，可以关闭窗口后重新选择场次。</p>}
              </div>
            ) : bookingStep === "screenings" ? (
              <>
                <p className="booking-intro">选择影院和开场时间</p>
                {isScreeningsLoading ? (
                  <div className="state-message">正在读取最新场次…</div>
                ) : screeningsError ? (
                  <div className="empty-state">{screeningsError}</div>
                ) : availableScreenings.length === 0 ? (
                  <div className="empty-state">当前没有可售场次，请稍后再来。</div>
                ) : (
                  <div className="screening-list">
                    {availableScreenings.map((screening) => (
                      <button className="screening-option" type="button" key={screening.id} disabled={isBookingAction} onClick={() => void chooseScreening(screening)}>
                        <span className="screening-time">{formatDateTime(screening.start_time)}</span>
                        <span className="screening-venue">{screeningVenue(screening)}</span>
                        <strong>¥{amount(screening.price)}</strong>
                      </button>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="seat-step-heading">
                  <button className="text-button" type="button" onClick={() => { setBookingStep("screenings"); setSelectedSeatIds([]); }}>← 返回场次</button>
                  <span>{selectedScreening ? `${formatDateTime(selectedScreening.start_time)} · ${screeningVenue(selectedScreening)}` : ""}</span>
                </div>
                <div className="seat-legend" aria-label="座位状态">
                  <span><i className="legend-seat available" />可选</span><span><i className="legend-seat selected" />已选</span><span><i className="legend-seat locked" />暂不可选</span>
                  <button className="text-button" type="button" disabled={isBookingAction} onClick={() => void reloadSeats()}>刷新座位</button>
                </div>
                <div className="screen-label">银幕方向</div>
                <div className="seat-map" aria-label="座位图">
                  {seatRows.map((rowNumber) => {
                    const rowSeats = seats.filter((seat) => seat.row_no === rowNumber).sort((a, b) => a.column_no - b.column_no);
                    const byColumn = new Map(rowSeats.map((seat) => [seat.column_no, seat]));
                    return (
                      <div className="seat-row" key={rowNumber}>
                        <span className="row-label">{rowNumber}排</span>
                        <div className="seat-row-grid" style={{ gridTemplateColumns: `repeat(${maxColumn}, minmax(25px, 1fr))` }}>
                          {Array.from({ length: maxColumn }, (_, index) => {
                            const seat = byColumn.get(index + 1);
                            if (!seat) return <span className="seat-gap" key={`gap-${rowNumber}-${index}`} />;
                            const status = seat.booking_status ?? seat.status;
                            const isSelected = selectedSeatIds.includes(seat.id);
                            return <button
                              className={`seat-button ${status === "AVAILABLE" ? "available" : "unavailable"} ${isSelected ? "selected" : ""}`}
                              type="button" key={seat.id} aria-label={`${seat.seat_code}${isSelected ? "，已选择" : ""}`}
                              title={`${seat.seat_code} · ${status === "AVAILABLE" ? "可选" : status === "LOCKED" ? "暂被锁定" : "已售"}`}
                              disabled={status !== "AVAILABLE"} onClick={() => toggleSeat(seat)}
                            >{seat.column_no}</button>;
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
                {seats.length === 0 && <div className="empty-state">当前影厅没有可用座位。</div>}
                <div className="booking-summary">
                  <div><span>{selectedSeatIds.length ? seats.filter((seat) => selectedSeatIds.includes(seat.id)).map((seat) => seat.seat_code).join("、") : "请选择座位"}</span><strong>¥{amount(Number(selectedScreening?.price ?? 0) * selectedSeatIds.length)}</strong></div>
                  <button className="primary-button" type="button" disabled={selectedSeatIds.length === 0 || isBookingAction} onClick={() => void createOrder()}>{isBookingAction ? "正在锁座…" : session ? "锁座并下单" : "登录后锁座下单"}</button>
                </div>
              </>
            )}
            {bookingMessage && <p className={bookingFailed ? "modal-feedback error" : "modal-feedback"}>{bookingMessage}</p>}
            {activeOrder && activeOrder.status !== "UNPAID" && <button className="secondary-button close-checkout" type="button" onClick={() => setIsBookingOpen(false)}>完成</button>}
          </section>
        </div>
      )}

      {ticketOrderNo && session && <TicketDialog orderNo={ticketOrderNo} token={session.token} request={apiRequest} onClose={() => setTicketOrderNo(null)} />}

      {isAuthOpen && (
        <div className="modal-backdrop auth-backdrop" role="presentation" onClick={() => setIsAuthOpen(false)}>
          <section className="auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" type="button" aria-label="关闭" onClick={() => setIsAuthOpen(false)}>×</button>
            <p className="eyebrow">{authMode === "login" ? "WELCOME BACK" : "JOIN CINEMA"}</p>
            <h2 id="auth-title">{authMode === "login" ? "登录 CINEMA" : "注册新账号"}</h2>
            <div className="auth-tabs" role="tablist" aria-label="登录或注册">
              <button type="button" role="tab" aria-selected={authMode === "login"} className={authMode === "login" ? "auth-tab active" : "auth-tab"} onClick={() => switchAuthMode("login")}>登录</button>
              <button type="button" role="tab" aria-selected={authMode === "register"} className={authMode === "register" ? "auth-tab active" : "auth-tab"} onClick={() => switchAuthMode("register")}>注册</button>
            </div>
            {authMode === "login" ? (
              <form className="auth-form" onSubmit={handleLogin}>
                <label>用户名<input value={loginName} onChange={(event) => setLoginName(event.target.value)} autoComplete="username" required /></label>
                <label>密码<input type="password" minLength={8} value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} autoComplete="current-password" required /></label>
                <button className="primary-button" type="submit" disabled={isSubmitting}>{isSubmitting ? "登录中" : "登录"}</button>
              </form>
            ) : (
              <form className="auth-form" onSubmit={handleRegister}>
                <label>用户名<input value={loginName} onChange={(event) => setLoginName(event.target.value)} autoComplete="username" required /></label>
                <label>密码（至少 8 位）<input type="password" minLength={8} maxLength={72} value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} autoComplete="new-password" required /></label>
                <label>确认密码<input type="password" minLength={8} maxLength={72} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" required /></label>
                <label>手机号（选填）<input value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="tel" /></label>
                <button className="primary-button" type="submit" disabled={isSubmitting}>{isSubmitting ? "注册中" : "注册"}</button>
              </form>
            )}
            {authMessage && <p className={authFailed ? "modal-feedback error" : "modal-feedback"}>{authMessage}</p>}
          </section>
        </div>
      )}
    </main>
  );
}

export { App };
