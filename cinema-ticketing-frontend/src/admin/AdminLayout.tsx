import { useEffect, useRef, type MouseEvent, type ReactNode } from "react";
import { ADMIN_PAGES, type AdminView } from "./routes";
import "./admin-shell.css";

type Props = {
  view: AdminView | null; username: string; navigate: (path: string) => void;
  signOut: () => void; openSecurity: () => void; children: ReactNode;
};

export default function AdminLayout({ view, username, navigate, signOut, openSecurity, children }: Props) {
  function follow(event: MouseEvent<HTMLAnchorElement>, path: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(path);
  }
  const page = ADMIN_PAGES.find((item) => item.id === view);
  const content = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${page?.label ?? "页面不存在"} · CINEMA 管理后台`;
    content.current?.focus({ preventScroll: true });
    return () => { document.title = previousTitle; };
  }, [page]);
  const groups = [...new Set(ADMIN_PAGES.map((item) => item.group))];
  return <div className="admin-shell">
    <a className="admin-skip-link" href="#admin-content">跳到管理内容</a>
    <aside className="admin-sidebar" aria-label="管理后台">
      <a className="brand admin-brand" href="/admin" onClick={(event) => follow(event, "/admin")}><span className="brand-mark">C</span><span>CINEMA<small>管理后台</small></span></a>
      <nav className="admin-side-nav" aria-label="后台管理导航">
        {groups.map((group) => <div className="admin-nav-group" key={group}><p>{group}</p>{ADMIN_PAGES.filter((item) => item.group === group).map((item) =>
          <a key={item.id} href={`/admin/${item.id}`} aria-current={view === item.id ? "page" : undefined} onClick={(event) => follow(event, `/admin/${item.id}`)}>{item.label}</a>)}</div>)}
      </nav>
      <a className="admin-back-link" href="/" onClick={(event) => follow(event, "/")}>返回观影首页 <span aria-hidden="true">↗</span></a>
    </aside>
    <div className="admin-main">
      <header className="admin-topbar">
        <div className="admin-breadcrumb"><span>管理后台</span><span aria-hidden="true">/</span><strong>{page?.label ?? "页面不存在"}</strong></div>
        <div className="admin-profile"><span className="admin-username" title={username}>{username}<small>管理员</small></span><button className="secondary-button" type="button" onClick={openSecurity}>个人安全</button><button className="secondary-button" type="button" onClick={signOut}>退出登录</button></div>
      </header>
      <label className="admin-mobile-nav">管理模块<select aria-label="管理模块" value={view ?? ""} onChange={(event) => navigate(`/admin/${event.target.value}`)}>{!view && <option value="" disabled>选择模块</option>}{ADMIN_PAGES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <main className="admin-content" id="admin-content" ref={content} tabIndex={-1}>{children}</main>
    </div>
  </div>;
}
