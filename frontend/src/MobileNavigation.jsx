import { useRef } from "react";
import { NavLink } from "react-router-dom";

export default function MobileNavigation({ logout }) {
  const dialog = useRef(null);
  const close = () => dialog.current?.close();
  return <>
    <nav className="mobile-navigation" aria-label="Основная навигация">
      {[["/", "▦", "Обзор"], ["/payments", "⇄", "Платежи"], ["/users", "◉", "Люди"], ["/projects", "◫", "Проекты"]].map(([to, icon, label]) => <NavLink key={to} to={to} end={to === "/"}><i aria-hidden="true">{icon}</i><span>{label}</span></NavLink>)}
      <button type="button" onClick={() => dialog.current.showModal()} aria-haspopup="dialog"><i aria-hidden="true">☰</i><span>Ещё</span></button>
    </nav>
    <dialog ref={dialog} className="mobile-menu" aria-labelledby="mobile-menu-title" onClick={event => { if (event.target === dialog.current) close(); }}>
      <div className="mobile-menu-content"><div className="mobile-menu-heading"><h2 id="mobile-menu-title">Рабочее пространство</h2><button type="button" onClick={close} aria-label="Закрыть меню" autoFocus>×</button></div>
        <nav aria-label="Дополнительные разделы">{[["/limits", "Лимиты и время"], ["/providers", "Подключения"], ["/support", "Поддержка"], ["/settings", "Настройки"]].map(([to, label]) => <NavLink key={to} to={to} onClick={close}>{label}<span aria-hidden="true">›</span></NavLink>)}</nav>
        <button type="button" className="mobile-logout" onClick={() => { close(); logout(); }}>Выйти из панели</button>
      </div>
    </dialog>
  </>;
}
