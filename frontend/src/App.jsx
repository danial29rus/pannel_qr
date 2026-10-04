import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, money } from "./api";
import "./payment-trace.css";

const PanelContext = createContext();
const usePanel = () => useContext(PanelContext);
const routes = [["/", "▦", "Обзор"], ["/payments", "⇄", "Журнал платежей"], ["/users", "◉", "Пользователи"], ["/limits", "⊡", "Лимиты и время"], ["/projects", "◫", "Проекты"], ["/providers", "◈", "Подключения"], ["/settings", "⚙", "Настройки"]];

function App() {
  const [projects, setProjects] = useState([]); const [projectId, setProjectId] = useState(localStorage.getItem("active-project") || ""); const [toast, setToast] = useState(""); const [authenticated, setAuthenticated] = useState(() => ["localhost", "127.0.0.1"].includes(window.location.hostname) || !!sessionStorage.getItem("panel-token"));
  const notice = (message) => { setToast(message); setTimeout(() => setToast(""), 3500); };
  const reloadProjects = async () => { try { const list = await api("/projects"); setProjects(list); if (!projectId && list[0]) setProjectId(list[0].id); } catch (e) { notice(e.message); } };
  useEffect(() => { if (authenticated) reloadProjects(); }, [authenticated]);
  useEffect(() => { if (projectId) localStorage.setItem("active-project", projectId); }, [projectId]);
  if (!authenticated) return <Login onLogin={() => setAuthenticated(true)}/>;
  return <PanelContext.Provider value={{ projects, projectId, setProjectId, reloadProjects, notice }}><div className="shell"><Sidebar/><main><Header/><Routes><Route path="/" element={<OperationsDashboard/>}/><Route path="/payments" element={<Payments/>}/><Route path="/users" element={<Users/>}/><Route path="/limits" element={<Limits/>}/><Route path="/projects" element={<Projects/>}/><Route path="/providers" element={<Providers/>}/><Route path="/analytics" element={<Analytics/>}/><Route path="/support" element={<Support/>}/><Route path="/settings" element={<Settings/>}/><Route path="*" element={<Navigate to="/" replace/>}/></Routes></main><div className={`toast ${toast ? "show" : ""}`}>{toast}</div></div></PanelContext.Provider>;
}

function Login({ onLogin }) { const [username,setUsername]=useState("admin"),[password,setPassword]=useState(""),[error,setError]=useState(""),[busy,setBusy]=useState(false); const submit=async e=>{e.preventDefault();setBusy(true);setError("");try{const r=await api("/auth/login",{method:"POST",body:JSON.stringify({username,password})});sessionStorage.setItem("panel-token",r.access_token);onLogin();}catch(e){setError(e.message)}finally{setBusy(false)}}; return <main className="login-page"><form className="card login-card" onSubmit={submit}><div className="brand"><b>◈</b>clear<span>pay</span></div><h2>Вход в панель</h2><p>Доступ только для авторизованных сотрудников.</p><label>Логин<input value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username"/></label><label>Пароль<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/></label>{error&&<small className="login-error">{error}</small>}<button className="primary" disabled={busy}>{busy?"Проверяем…":"Войти"}</button></form></main>; }

function Sidebar() { return <aside><div className="brand"><b>◈</b>clear<span>pay</span></div><small className="side-caption">РАБОЧЕЕ ПРОСТРАНСТВО</small><div className="workspace">Основной кабинет <b>⌄</b></div><nav>{routes.slice(0, -1).map(([to, icon, name]) => <NavLink key={to} to={to} end={to === "/"}><i>{icon}</i>{name}</NavLink>)}</nav><div className="bottom-nav"><NavLink to="/settings"><i>⚙</i>Настройки</NavLink><div className="profile"><b>АД</b><span>Администратор<small>admin</small></span><i>⋮</i></div></div></aside>; }
function Header() { const { projects, projectId, setProjectId } = usePanel(); const navigate = useNavigate(); return <header><div><small>ОПЕРАЦИОННЫЙ ЦЕНТР</small><h1>Контроль платежей</h1></div><div className="head-actions"><label>Проект<select value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">Выберите проект</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " · выключен"}</option>)}</select></label><button className="notification">♧<sup>3</sup></button><button className="primary" onClick={() => navigate("/payments")}>+ Новый платёж</button></div></header>; }
function PageHeader({ title, text, action }) { return <div className="page-header"><div><h2>{title}</h2><p>{text}</p></div>{action}</div>; }
function Empty({ text = "Выберите проект для просмотра данных." }) { return <div className="empty">◌<p>{text}</p></div>; }
function useSummary(days = 30) { const { projectId, notice } = usePanel(); const [summary, setSummary] = useState(null); useEffect(() => { if (!projectId) return setSummary(null); const to = new Date(), from = new Date(to); from.setDate(to.getDate() - days); api(`/dashboard/summary?project_id=${projectId}&currency=RUB&from_date=${from.toISOString()}&to_date=${to.toISOString()}`).then(setSummary).catch(e => notice(e.message)); }, [projectId, days]); return summary; }

function Overview() { const [days, setDays] = useState(30); const summary = useSummary(days); const { projectId } = usePanel(); const rate = summary?.payment_count ? Math.round(summary.success_count / summary.payment_count * 100) : 0; return <section><div className="guard-note"><b>✦ Guard’ы включаются на сервере</b><span>Скорость заявок, очередь и лимиты проверяются до адаптера.</span></div><div className="period">{[[1,"Сегодня"],[7,"7 дней"],[30,"30 дней"]].map(([v,n]) => <button key={v} onClick={() => setDays(v)} className={days === v ? "chosen" : ""}>{n}</button>)}<span>RUB · последние {days} дней</span></div><div className="metrics"><Metric label="ОБОРОТ" value={summary ? money(summary.paid_by_clients) : "—"} suffix="только успешно оплаченные" color="blue"/><Metric label="ЗАЧИСЛЕНО" value={summary ? money(summary.credited_by_payments) : "—"} suffix="только успешно оплаченные" color="green"/><Metric label="В ОЖИДАНИИ" value={summary?.pending_count ?? "—"} suffix="created · pending · processing" color="violet"/><Metric label="СТАТУСЫ" value={summary ? `${rate}%` : "—"} suffix={summary ? `${summary.success_count} успешно · ${summary.failed_count} завершились ошибкой` : "Нет данных"} color="orange"/></div><div className="dashboard-grid"><article className="card chart-card"><CardTitle title="Динамика оборота" text="Подтверждённые платежи"/><div className="chart"><div className="chart-lines"/><svg viewBox="0 0 700 200" preserveAspectRatio="none"><path d="M0 165 C50 130 74 168 122 125 S195 140 238 95 S302 119 350 77 S415 90 455 45 S535 89 575 55 S645 78 700 18 V200H0Z" fill="url(#gradient)"/><path d="M0 165 C50 130 74 168 122 125 S195 140 238 95 S302 119 350 77 S415 90 455 45 S535 89 575 55 S645 78 700 18" fill="none" stroke="#8392ff" strokeWidth="3"/><defs><linearGradient id="gradient" x1="0" x2="0" y1="0" y2="1"><stop stopColor="#6577ff" stopOpacity=".38"/><stop offset="1" stopColor="#6577ff" stopOpacity="0"/></linearGradient></defs></svg></div></article><article className="card"><CardTitle title="Статус проекта" text="Доступность контуров"/><Status title="PostgreSQL" detail="База данных" state="Подключена" ok/><Status title="Операционные guard’ы" detail="Скорость · очередь · интервал" state={projectId ? "Проверить" : "Нет проекта"} ok={!!projectId}/><Status title="Платёжные адаптеры" detail="Провайдеры" state="Настройте"/></article></div></section>; }
function Metric({ label, value, suffix, color }) { return <article className="metric"><div><small>{label}</small><i className={color}>✦</i></div><strong>{value}</strong><p>{suffix}</p></article>; }
function CardTitle({ title, text }) { return <div className="card-title"><div><h3>{title}</h3><p>{text}</p></div></div>; }
function Status({ title, detail, state, ok }) { return <div className="status-row"><b className={ok ? "good" : "warn"}>{ok ? "✓" : "!"}</b><span>{title}<small>{detail}</small></span><em>{state}</em></div>; }

const stateLabel = { created:"Создан", pending:"Ожидает", processing:"Обработка", succeeded:"Успешно", failed:"Ошибка", cancelled:"Отменён", refunded:"Возврат" };
const timeLabel = value => value ? new Date(value).toLocaleString("ru-RU") : "—";
const json = value => JSON.stringify(value ?? {}, null, 2);

function Payments() {
  const { projectId, notice } = usePanel();
  const [items, setItems] = useState([]); const [query, setQuery] = useState(""); const [status, setStatus] = useState("all"); const [selected, setSelected] = useState(null); const [trace, setTrace] = useState(null); const [loadingTrace, setLoadingTrace] = useState(false);
  const reload = async () => { if (!projectId) return setItems([]); try { setItems(await api(`/transactions?project_id=${projectId}&limit=100`)); } catch (error) { notice(error.message); } };
  useEffect(() => { setSelected(null); setTrace(null); reload(); }, [projectId]);
  const open = async item => { if (selected === item.id) { setSelected(null); setTrace(null); return; } setSelected(item.id); setTrace(null); setLoadingTrace(true); try { setTrace(await api(`/transactions/${item.id}/trace`)); } catch (error) { notice(error.message); } finally { setLoadingTrace(false); } };
  const visible = items.filter(item => {
    const needle = query.trim().toLowerCase();
    return (status === "all" || item.state === status) && (!needle || [item.id, item.external_id, item.external_order_id, item.description, item.provider_name, item.order_reference].filter(Boolean).join(" ").toLowerCase().includes(needle));
  });
  return <section><PageHeader title="Журнал платежей" text="Каждый платёж: площадка → платёжка → webhook → финальный callback." action={<button onClick={reload}>↻ Обновить</button>}/><article className="card table-card"><div className="table-filter"><input value={query} onChange={event => setQuery(event.target.value)} placeholder="ID, заказ, платёжка или описание"/><select value={status} onChange={event => setStatus(event.target.value)}><option value="all">Все статусы</option>{Object.entries(stateLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div><div className="table head"><span>Платёж / подключение</span><span>Сумма</span><span>Статус</span><span>Создан</span></div>{visible.length ? visible.map(item => <Transaction key={item.id} item={item} open={selected === item.id} onOpen={() => open(item)} trace={trace} loading={loadingTrace && selected === item.id}/>) : <Empty text="Операций по этому фильтру пока нет."/>}</article></section>;
}
function Transaction({ item, open, onOpen, trace, loading }) { const label = stateLabel[item.state] || item.state; return <><button className={`table transaction-row ${open ? "selected" : ""}`} onClick={onOpen}><span><b>{item.external_id || item.external_order_id || item.id.slice(0, 13)}</b><small>{item.provider_name} · {item.order_reference || item.description || "прямой платёж"}</small></span><span>{money(item.amount)} {item.currency}</span><span><i className={`tag ${item.state}`}>{label}</i></span><span>{timeLabel(item.created_at)} <small className="open-trace">{open ? "Скрыть маршрут" : "Открыть маршрут"}</small></span></button>{open && <PaymentTrace trace={trace} loading={loading}/>}</>; }
function PaymentTrace({ trace, loading }) { if (loading) return <div className="payment-trace loading-trace">Загружаем техническую историю платежа…</div>; if (!trace) return <div className="payment-trace loading-trace">Не удалось загрузить историю.</div>; return <div className="payment-trace"><div className="trace-summary"><span><small>ПЛАТЁЖКА</small><b>{trace.payment.provider_name}</b><em>{trace.payment.provider_code}</em></span><span><small>ЗАЯВКА MATISON</small><b>{trace.payment.merchant_transaction_id || trace.payment.external_order_id || "Не внешний заказ"}</b><em>{trace.payment.merchant_transaction_id ? "merchant_transaction_id" : trace.payment.order_reference || "—"}</em></span><span><small>ПОЛЬЗОВАТЕЛЬ MULEN</small><b>{trace.customer?.full_name || "Не выбран"}</b><em>{trace.customer?.email || "—"}</em></span><span><small>ОПИСАНИЕ</small><b>{trace.payment.description || "—"}</b><em>{trace.payment.user_id || "—"}</em></span><span><small>ТЕКУЩИЙ СТАТУС</small><b>{stateLabel[trace.payment.state] || trace.payment.state}</b><em>{trace.payment.external_id || "ID провайдера ещё не получен"}</em></span></div><div className="trace-line">{trace.timeline.length ? trace.timeline.map((step, index) => <article className={`trace-step ${step.outcome && step.outcome !== "success" ? "trace-error" : ""}`} key={step.id}><i>{index + 1}</i><div><b>{step.title}</b><p>{timeLabel(step.created_at)}{step.attempt ? ` · попытка ${step.attempt}` : ""}{step.http_status ? ` · HTTP ${step.http_status}` : ""}{step.state ? ` · ${stateLabel[step.previous_state] || step.previous_state || "—"} → ${stateLabel[step.state] || step.state}` : ""}</p>{step.error && <strong>{step.error}</strong>}{step.payload && <details><summary>Технические данные запроса и ответа</summary><pre>{json(step.payload)}</pre></details>}</div><em>{step.outcome === "success" ? "OK" : step.outcome || "событие"}</em></article>) : <Empty text="Для этого платежа пока есть только карточка, без событий."/>}</div></div>; }

function Limits() {
  const { projectId, notice } = usePanel();
  const [policy, setPolicy] = useState(null);
  const [form, setForm] = useState(null);
  useEffect(() => {
    if (!projectId) return setPolicy(null);
    api(`/projects/${projectId}/operational-policy`).then(p => { setPolicy(p); setForm(p); }).catch(e => notice(e.message));
  }, [projectId]);
  const save = async event => {
    event.preventDefault();
    try {
      const result = await api(`/projects/${projectId}/operational-policy`, {
        method:"PUT",
        body:JSON.stringify({
          ...form,
          max_transactions_10m:Number(form.max_transactions_10m),
          max_transactions_hour:Number(form.max_transactions_hour),
          max_transactions_day:Number(form.max_transactions_day),
          max_all_transactions_hour:numberOrNull(form.max_all_transactions_hour),
          max_all_transactions_day:numberOrNull(form.max_all_transactions_day),
          max_pending_transactions:Number(form.max_pending_transactions),
          daily_amount_limit:Number(form.daily_amount_limit),
          cooldown_minutes:Number(form.cooldown_minutes),
        }),
      });
      setPolicy(result); setForm(result); notice("Лимиты сохранены");
    } catch (error) { notice(error.message); }
  };
  if (!policy || !form) return <section><PageHeader title="Лимиты и время" text="Настройки проверяются перед каждым платежом."/><Empty/></section>;
  const set = key => event => setForm({ ...form, [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value });
  return <section>
    <PageHeader title="Лимиты и время" text="Успешные оплаты, все заявки и очередь контролируются раздельно." action={<span className="secure">✓ server-side guard</span>}/>
    <div className="limit-grid">
      <article className="card policy">
        <CardTitle title="Лимиты проекта" text="Успешные лимиты не включают ошибки; жёсткий лимит заявок включает все статусы."/>
        <form onSubmit={save}><div className="inputs">
          <Field label="Успешных за 10 минут" value={form.max_transactions_10m} onChange={set("max_transactions_10m")} hint="Скользящие 10 минут"/>
          <Field label="Успешных за час" value={form.max_transactions_hour} onChange={set("max_transactions_hour")} hint="Скользящий час"/>
          <Field label="Успешных за день" value={form.max_transactions_day} onChange={set("max_transactions_day")} hint="Календарный день по Москве"/>
          <Field label="Всех заявок за час" value={form.max_all_transactions_hour ?? ""} onChange={set("max_all_transactions_hour")} hint="Любой статус; пусто — без лимита"/>
          <Field label="Всех заявок за день" value={form.max_all_transactions_day ?? ""} onChange={set("max_all_transactions_day")} hint="Календарный день по Москве; любой статус"/>
          <Field label="Одновременно в ожидании" value={form.max_pending_transactions} onChange={set("max_pending_transactions")} hint="created, pending и processing"/>
          <Field label="Сумма успешных за день" value={form.daily_amount_limit} onChange={set("daily_amount_limit")} hint="Не включает ожидающие и ошибки"/>
          <label>Интервал между успешными, минут<input type="number" min="0" max="1440" value={form.cooldown_minutes} onChange={set("cooldown_minutes")}/><small>0 — паузы нет.</small></label>
        </div><label className="toggle"><input type="checkbox" checked={form.is_active} onChange={set("is_active")}/><i/>Применять лимиты к новым платежам</label><div className="submit-row"><small>Лимиты не меняют уже созданные заказы.</small><button className="primary">Сохранить</button></div></form>
      </article>
      <article className="card"><CardTitle title="Как считаются показатели" text="Успехи, все заявки и очередь разделены."/>
        <Status ok={form.is_active} title="Успешные" detail={`${form.max_transactions_10m}/10 мин · ${form.max_transactions_hour}/час · ${form.max_transactions_day}/день`} state="Лимиты"/>
        <Status ok={form.is_active} title="Все заявки" detail={`${form.max_all_transactions_hour || "∞"}/час · ${form.max_all_transactions_day || "∞"}/день`} state="Жёсткий фильтр"/>
        <Status ok={form.is_active} title="Очередь" detail={`до ${form.max_pending_transactions} одновременно`} state="Ожидание"/>
        <Status ok={form.is_active} title="Оборот" detail={`${form.daily_amount_limit} в валюте платежа`} state="Только успешно"/>
        <Status ok={form.is_active} title="Пауза" detail={form.cooldown_minutes ? `${form.cooldown_minutes} мин.` : "без паузы"} state="После успеха"/>
      </article>
    </div>
  </section>;
}
function Field({ label, value, onChange, hint }) { return <label>{label}<input type="number" min="0" step="0.01" value={value} onChange={onChange}/><small>{hint}</small></label>; }

function Projects() {
  const { projects, reloadProjects, setProjectId, notice } = usePanel();
  const [creating, setCreating] = useState(!projects.length); const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name:"Wordkit Studio", external_key:"wordkit-studio", owner_name:"", owner_email:"", business_name:"Wordkit Studio" });
  const set = key => event => setForm({ ...form, [key]:event.target.value });
  const toggle = async p => { try { await api(`/projects/${p.id}/activation`, { method:"PATCH", body:JSON.stringify({is_active:!p.is_active}) }); await reloadProjects(); notice(`Проект ${p.is_active ? "выключен" : "включён"}`); } catch (e) { notice(e.message); } };
  const savePlatformRate = async (p, value) => { try { await api(`/projects/${p.id}/commission`, { method:"PATCH", body:JSON.stringify({default_platform_fee_percent:Number(value || 0)}) }); await reloadProjects(); notice("Ставка площадки сохранена"); } catch (e) { notice(e.message); } };
  const create = async event => {
    event.preventDefault(); setBusy(true);
    try {
      const owner = await api("/users", { method:"POST", body:JSON.stringify({ full_name:form.owner_name, email:form.owner_email, business_name:form.business_name }) });
      const project = await api("/projects", { method:"POST", body:JSON.stringify({ owner_id:owner.id, name:form.name, external_key:form.external_key }) });
      await reloadProjects(); setProjectId(project.id); setCreating(false); notice("Проект создан. Теперь подключите к нему платёжку.");
    } catch (error) { notice(error.message); } finally { setBusy(false); }
  };
  return <section><PageHeader title="Проекты" text="Сначала создайте проект, затем добавьте в него одну или несколько платёжек." action={<button className="primary" onClick={() => setCreating(true)}>+ Новый проект</button>}/>{creating && <article className="card create-project"><CardTitle title="Новый проект" text="Владелец создаётся автоматически вместе с первым проектом."/><form onSubmit={create}><div className="project-create-fields"><label>Название проекта<input required value={form.name} onChange={set("name")} placeholder="Wordkit Studio"/></label><label>Системный ключ<input required value={form.external_key} onChange={set("external_key")} pattern="[a-zA-Z0-9_-]+" placeholder="wordkit-studio"/><small>Только латиница, цифры, дефис и подчёркивание.</small></label><label>Компания владельца<input required value={form.business_name} onChange={set("business_name")} placeholder="Wordkit Studio"/></label><label>Имя владельца<input required value={form.owner_name} onChange={set("owner_name")} placeholder="Администратор"/></label><label>Е-mail для платежей<input required type="email" value={form.owner_email} onChange={set("owner_email")} placeholder="you@workkit-studio.ru"/><small>MulenPay требует e-mail у покупателя; для теста можно указать свой.</small></label></div><div className="submit-row"><button type="button" onClick={() => setCreating(false)}>Отмена</button><button className="primary" disabled={busy}>{busy ? "Создаём…" : "Создать проект"}</button></div></form></article>}<article className="card projects">{projects.length ? projects.map(p => <div className="project-row" key={p.id}><div className="project-mark">{p.name[0]?.toUpperCase()}</div><span><b>{p.name}</b><small>{p.external_key} · создан {new Date(p.created_at).toLocaleDateString("ru-RU")}</small></span><label className="inline-rate">Ставка площадки<input type="number" min="0" max="100" step="0.01" defaultValue={p.default_platform_fee_percent} onBlur={e => savePlatformRate(p, e.target.value)}/><small>% с оборота</small></label><i className={`tag ${p.is_active ? "succeeded" : "failed"}`}>{p.is_active ? "Активен" : "Выключен"}</i><button onClick={() => toggle(p)}>{p.is_active ? "Выключить" : "Включить"}</button></div>) : <Empty text="Создайте первый проект формой выше."/>}</article></section>;
}
function Analytics() { const summary = useSummary(30); const average = summary?.payment_count ? Number(summary.paid_by_clients) / summary.payment_count : 0; return <section><PageHeader title="Аналитика" text="Сводка по платежам за последние 30 дней." action={<button>Скачать CSV ↓</button>}/><div className="analytics"><Metric label="КОНВЕРСИЯ" value={summary?.payment_count ? `${Math.round(summary.success_count / summary.payment_count * 100)}%` : "—"} suffix="Успешные операции" color="green"/><Metric label="СРЕДНИЙ ЧЕК" value={summary ? money(average) : "—"} suffix="USDT" color="blue"/><article className="card insight"><h3>Расширенная аналитика</h3><p>После интеграции реальных адаптеров появятся срезы по провайдерам, валютам, причинам отказов и фактическому времени обработки.</p></article></div></section>; }
function Support() { const { notice } = usePanel(); const [items, setItems] = useState([]); const [current, setCurrent] = useState(null); const [messages, setMessages] = useState([]); const [draft, setDraft] = useState(""); const [sending, setSending] = useState(false); useEffect(() => { api("/support/conversations").then(setItems).catch(e => notice(e.message)); }, []); const open = async item => { setCurrent(item); setDraft(""); try { setMessages(await api(`/support/conversations/${item.id}/messages`)); } catch(e) { notice(e.message); } }; const send = async () => { const body = draft.trim(); if (!current || !body || sending) return; setSending(true); try { const result = await api(`/support/conversations/${current.id}/messages`, { method:"POST", body:JSON.stringify({ body, author_type:"operator" }) }); setMessages(previous => [...previous, { id:result.id, author_type:"operator", body, created_at:result.created_at }]); setDraft(""); notice("Ответ добавлен в диалог"); } catch (error) { notice(error.message); } finally { setSending(false); } }; return <section><PageHeader title="Поддержка" text="Диалоги операторов с пользователями."/><div className="chat"><article className="card inbox"><b>ОБРАЩЕНИЯ</b>{items.length ? items.map(i => <button className={current?.id === i.id ? "selected" : ""} onClick={() => open(i)} key={i.id}><b>{i.user_full_name}</b>{i.subject}<small>{i.user_email || i.user_telegram_username || "без контакта"} · {i.status} · {new Date(i.created_at).toLocaleDateString("ru-RU")}</small></button>) : <Empty text="Открытых обращений нет."/>}</article><article className="card dialogue">{current ? <><CardTitle title={current.subject} text={`${current.user_full_name} · ${current.user_email || current.user_telegram_username || "без контакта"} · ${current.status}`}/><div className="messages">{messages.map(m => <p className={m.author_type} key={m.id}>{m.body}<small>{new Date(m.created_at).toLocaleString("ru-RU")}</small></p>)}</div><div className="reply"><input value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter") send(); }} placeholder="Ответ оператором" maxLength="10000"/><button className="primary" onClick={send} disabled={!draft.trim() || sending}>{sending ? "Отправка…" : "Отправить"}</button></div></> : <Empty text="Выберите обращение слева."/>}</article></div></section>; }
function Settings() { const { notice, projectId, projects, reloadProjects } = usePanel(); const [token, setToken] = useState(sessionStorage.getItem("panel-token") || ""); const [external, setExternal] = useState({ external_callback_url:"", external_incoming_token:"", external_callback_secret:"", status_check_interval_seconds:"30", payment_expiry_minutes:"30" }); const saveExternal = async e => { e.preventDefault(); if (!projectId) return notice("Сначала выберите проект"); try { await api(`/projects/${projectId}/external-platform`, { method:"PUT", body:JSON.stringify({ ...external, status_check_interval_seconds:Number(external.status_check_interval_seconds), payment_expiry_minutes:Number(external.payment_expiry_minutes) }) }); await reloadProjects(); setExternal({ ...external, external_incoming_token:"", external_callback_secret:"" }); notice("Внешняя площадка настроена"); } catch(error) { notice(error.message); } }; const key = projects.find(p => p.id === projectId)?.external_key || "project-key"; return <section><PageHeader title="Настройки" text="Доступ, внешний контур и безопасный запуск."/><div className="settings"><article className="card"><h3>Токен панели</h3><p>В production включите <code>ENFORCE_AUTH=true</code>. Токен живёт только в текущей вкладке браузера.</p><div className="token"><input value={token} onChange={e => setToken(e.target.value)} placeholder="X-Panel-Token" type="password"/><button className="primary" onClick={() => { sessionStorage.setItem("panel-token", token); notice("Токен сохранён для вкладки"); }}>Сохранить</button></div></article><article className="card"><h3>Домен и порты</h3><p>React dev-сервер: <code>15173</code>; API: <code>18080</code>; PostgreSQL: <code>55432</code>. Для домена используйте Nginx и TLS.</p><code>panel.example.com → 127.0.0.1:15173</code></article></div><article className="card external-config"><CardTitle title="Внешняя площадка" text={projectId ? `Настройка входящих заказов для ${projects.find(p => p.id === projectId)?.name || "проекта"}. Секреты после сохранения не показываются.` : "Выберите проект сверху."}/><form onSubmit={saveExternal}><div className="provider-fields"><label>URL для финальных статусов<input required type="url" placeholder="https://platform.example/payments/status" value={external.external_callback_url} onChange={e => setExternal({...external,external_callback_url:e.target.value})}/></label><label>Токен входящих заказов<input required type="password" minLength="16" value={external.external_incoming_token} onChange={e => setExternal({...external,external_incoming_token:e.target.value})}/></label><label>Секрет подписи callback<input required type="password" minLength="16" value={external.external_callback_secret} onChange={e => setExternal({...external,external_callback_secret:e.target.value})}/></label><label>Проверять статус раз в, секунд<input required type="number" min="10" max="3600" value={external.status_check_interval_seconds} onChange={e => setExternal({...external,status_check_interval_seconds:e.target.value})}/></label><label>Закрыть неоплаченный заказ через, минут<input required type="number" min="5" max="10080" value={external.payment_expiry_minutes} onChange={e => setExternal({...external,payment_expiry_minutes:e.target.value})}/></label></div><small className="integration-url">Входящий URL: <code>/api/v1/external/{key}/orders</code> · заголовок <code>X-Platform-Token</code></small><div className="submit-row"><small>По умолчанию: проверка раз в 30 секунд, закрытие через 30 минут.</small><button className="primary" disabled={!projectId}>Сохранить контур</button></div></form></article></section>; }

function RoutingAnalytics() {
  const { notice } = usePanel();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const reload = async () => {
    setLoading(true);
    try { setProjects(await api("/analytics/projects")); } catch (error) { notice(error.message); } finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, []);
  const toggleRoute = async (route) => {
    try { await api(`/provider-routes/${route.id}/activation`, { method: "PATCH", body: JSON.stringify({ is_active: !route.is_active }) }); await reload(); notice(`Маршрут ${route.is_active ? "выключен" : "включён"}`); } catch (error) { notice(error.message); }
  };
  if (loading) return <section><PageHeader title="Аналитика маршрутов" text="Загружаем проекты, лимиты и подключённые платёжки…"/><Empty text="Загрузка…"/></section>;
  return <section className="routing-page"><PageHeader title="Аналитика маршрутов" text="Все проекты, лимиты и состояние подключённых платёжных систем." action={<button onClick={reload}>↻ Обновить</button>}/>{projects.length ? projects.map((item) => <article className="route-project card" key={item.project.id}><div className="route-project-head"><div><div className="project-label"><span className={item.project.is_active ? "project-on" : "project-off"}>{item.project.is_active ? "● Активен" : "● Выключен"}</span><small>{item.project.external_key}</small></div><h3>{item.project.name}</h3></div><div className="route-project-summary"><span>{item.provider_routes.filter(route => route.is_active).length} активных маршрутов</span><span>{item.financial_limits.filter(limit => limit.is_active).length} фин. лимитов</span></div></div><div className="route-limits"><div><small>ЛИМИТЫ ПРОЕКТА</small>{item.financial_limits.length ? item.financial_limits.map(limit => <p key={limit.id}>{limit.period} · {limit.direction} <b>{money(limit.amount)} {limit.currency}</b></p>) : <p>Финансовые лимиты не заданы</p>}</div><div><small>ОПЕРАЦИОННАЯ ПОЛИТИКА</small>{item.operational_policy ? <p>{item.operational_policy.is_active ? "Включена" : "Выключена"} · {item.operational_policy.amount_min}—{item.operational_policy.amount_max} · пауза {item.operational_policy.cooldown_minutes || 0} мин.</p> : <p>Не настроена</p>}</div></div><div className="route-table"><div className="route-row route-head"><span>Платёжка / маршрут</span><span>Окно</span><span>День</span><span>Неделя</span><span>Статус</span><span/></div>{item.provider_routes.length ? item.provider_routes.map(route => <div className="route-row" key={route.id}><span><b>{route.provider_name}</b><small>{route.name} · priority {route.priority} · вес {route.weight}</small></span><span>{route.available_from && route.available_to ? `${route.available_from.slice(0,5)}—${route.available_to.slice(0,5)}` : "24/7"}<small>{route.min_amount ?? "—"}—{route.max_amount ?? "—"}</small></span><span>{money(route.daily_used_amount)} / {route.daily_amount_limit ? money(route.daily_amount_limit) : "∞"}<small>{route.daily_used_transactions} / {route.daily_transactions_limit ?? "∞"} операций</small></span><span>{money(route.weekly_used_amount)} / {route.weekly_amount_limit ? money(route.weekly_amount_limit) : "∞"}<small>{route.weekly_used_transactions} / {route.weekly_transactions_limit ?? "∞"} операций</small></span><span><i className={`tag ${route.is_available ? "succeeded" : "failed"}`}>{route.is_available ? "Доступен" : route.unavailable_reason || "Выключен"}</i></span><button className="route-switch" onClick={() => toggleRoute(route)}>{route.is_active ? "Выключить" : "Включить"}</button></div>) : <Empty text="К этому проекту не подключена ни одна платёжка."/>}</div></article>) : <Empty text="Нет проектов. Создайте проект, подключите провайдера и добавьте маршрут."/>}</section>;
}

function Providers() {
  const { projectId, projects, notice } = usePanel();
  const [providers, setProviders] = useState([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ code:"", name:"", adapter_type:"mulenpay", base_url:"https://api.mulenpay.com/api", shop_id:"", api_key:"", secret_key:"", callback_token:"", provider_fee_percent:"0" });
  const reload = async () => { try { setProviders(await api("/providers")); } catch (error) { notice(error.message); } };
  useEffect(() => { reload(); }, []);
  const set = key => event => setForm({ ...form, [key]:event.target.value });
  const create = async event => {
    event.preventDefault(); setBusy(true);
    try {
      const isMulen = form.adapter_type === "mulenpay";
      await api("/providers", { method:"POST", body:JSON.stringify({ code:form.code, name:form.name, adapter_type:form.adapter_type, provider_fee_percent:Number(form.provider_fee_percent || 0), settings:isMulen ? { base_url:form.base_url, callback_token:form.callback_token } : {}, credentials_encrypted:isMulen ? { api_key:form.api_key, secret_key:form.secret_key, shop_id:form.shop_id } : {} }) });
      setForm({ ...form, code:"", name:"", shop_id:"", api_key:"", secret_key:"", callback_token:"" }); await reload(); notice("Провайдер создан. Привяжите его к проекту ниже.");
    } catch (error) { notice(error.message); } finally { setBusy(false); }
  };
  const connect = async provider => {
    if (!projectId) return notice("Сначала выберите проект в верхней панели");
    try { await api(`/projects/${projectId}/provider-routes`, { method:"POST", body:JSON.stringify({ provider_id:provider.id, name:`${provider.name} · основной`, priority:100, weight:100 }) }); notice("Подключение добавлено к выбранному проекту"); } catch (error) { notice(error.message); }
  };
  const saveProviderRate = async (provider, value) => { try { await api(`/providers/${provider.id}/commission`, { method:"PATCH", body:JSON.stringify({provider_fee_percent:Number(value || 0)}) }); await reload(); notice("Ставка провайдера сохранена"); } catch (error) { notice(error.message); } };
  const isMulen = form.adapter_type === "mulenpay";
  return <section className="providers-page"><PageHeader title="Провайдеры и подключения" text="Ключи принадлежат конкретному подключению. После сохранения они не возвращаются в интерфейс."/><div className="provider-layout"><article className="card provider-form"><CardTitle title="Новое подключение" text="Сначала создайте набор ключей, затем привяжите его к проекту."/><form onSubmit={create}><div className="provider-fields"><label>Адаптер<select value={form.adapter_type} onChange={set("adapter_type")}><option value="mulenpay">MulenPay · hosted checkout</option><option value="demo">Demo · локальная проверка</option></select></label><label>Комиссия провайдера, %<input type="number" min="0" max="100" step="0.01" value={form.provider_fee_percent} onChange={set("provider_fee_percent")}/><small>Себестоимость обработки</small></label><label>Название<input required value={form.name} onChange={set("name")} placeholder="MulenPay · проект Alpha"/></label><label>Системный код<input required value={form.code} onChange={set("code")} pattern="[a-z0-9_-]+" placeholder="mulen-alpha"/></label>{isMulen && <><label>API URL<input required value={form.base_url} onChange={set("base_url")} placeholder="https://…"/></label><label>Shop ID<input required value={form.shop_id} onChange={set("shop_id")} inputMode="numeric"/></label><label>API key<input required type="password" value={form.api_key} onChange={set("api_key")} autoComplete="new-password"/></label><label>Secret key<input required type="password" value={form.secret_key} onChange={set("secret_key")} autoComplete="new-password"/></label><label>Callback token <small>необязательно</small><input type="password" value={form.callback_token} onChange={set("callback_token")} autoComplete="new-password"/></label></>} </div><button className="primary" disabled={busy}>{busy ? "Сохраняем…" : "Создать подключение"}</button></form></article><article className="card provider-help"><CardTitle title="Экономика маршрута" text="Прибыль считается отдельно для каждого проекта и ключей."/><Status ok title="Ставка провайдера" detail="Себестоимость конкретного набора ключей" state="Расход"/><Status ok title="Ставка площадки" detail="Задаётся в проекте и применяется по умолчанию" state="Доход"/><Status title="Расчётная прибыль" detail="Оборот × (ставка площадки − ставка провайдера)" state="Прогноз"/></article></div><article className="card provider-list"><div className="provider-list-head"><CardTitle title="Сохранённые подключения" text={projectId ? `Можно добавить в проект ${projects.find(item => item.id === projectId)?.name || ""}` : "Выберите проект, чтобы добавить маршрут"}/><button onClick={reload}>↻ Обновить</button></div>{providers.length ? providers.map(provider => <div className="provider-row" key={provider.id}><span className="provider-icon">{provider.adapter_type === "mulenpay" ? "M" : "D"}</span><span><b>{provider.name}</b><small>{provider.code} · {provider.adapter_type} · создан {new Date(provider.created_at).toLocaleDateString("ru-RU")}</small></span><label className="inline-rate">Комиссия<input type="number" min="0" max="100" step="0.01" defaultValue={provider.provider_fee_percent} onBlur={e => saveProviderRate(provider, e.target.value)}/><small>% расход</small></label><i className={`tag ${provider.is_active ? "succeeded" : "failed"}`}>{provider.is_active ? "Активен" : "Выключен"}</i><button className="route-switch" onClick={() => connect(provider)}>+ В проект</button></div>) : <Empty text="Подключений ещё нет."/>}</article></section>;
}

function OperationsAnalytics() {
  const { notice } = usePanel();
  const [items, setItems] = useState([]); const [loading, setLoading] = useState(true);
  const reload = async () => { setLoading(true); try { setItems(await api("/analytics/projects")); } catch (error) { notice(error.message); } finally { setLoading(false); } };
  useEffect(() => { reload(); }, []);
  const toggleRoute = async route => { try { await api(`/provider-routes/${route.id}/activation`, { method:"PATCH", body:JSON.stringify({ is_active:!route.is_active }) }); await reload(); notice(`Маршрут ${route.is_active ? "выключен" : "включён"}`); } catch (error) { notice(error.message); } };
  const routes = items.flatMap(item => item.provider_routes.map(route => ({ ...route, project:item.project })));
  const active = routes.filter(route => route.is_active); const used = routes.reduce((sum, route) => sum + Number(route.daily_used_amount || 0), 0); const capacity = routes.reduce((sum, route) => sum + Number(route.daily_amount_limit || 0), 0); const profit = routes.reduce((sum, route) => sum + Number(route.daily_profit || 0), 0); const ready = routes.filter(route => route.is_available).length;
  if (loading) return <section><PageHeader title="Операционная аналитика" text="Загружаем маршруты, лимиты и загрузку…"/><Empty text="Загрузка…"/></section>;
  return <section className="operations-page"><PageHeader title="Операционный центр" text="Управление всеми проектами, подключениями, лимитами и расчётной прибылью в одном экране." action={<button onClick={reload}>↻ Обновить</button>}/><div className="network-kpis five"><Metric label="ПРОЕКТЫ" value={items.length} suffix="всего контуров" color="blue"/><Metric label="МАРШРУТЫ" value={active.length} suffix={`${ready} доступны сейчас`} color="green"/><Metric label="ОБОРОТ ЗА ДЕНЬ" value={money(used)} suffix="по всем маршрутам" color="violet"/><Metric label="ПРИБЫЛЬ ЗА ДЕНЬ" value={money(profit)} suffix="по текущим ставкам" color="green"/><Metric label="ДНЕВНАЯ ЁМКОСТЬ" value={capacity ? money(capacity) : "∞"} suffix="заданные лимиты" color="orange"/></div><article className="card network-board"><div className="network-board-head"><div><small>СЕТЬ ПОДКЛЮЧЕНИЙ</small><h3>Маршруты, лимиты и экономика по проектам</h3></div><span className="live-dot">● live из PostgreSQL</span></div>{items.length ? items.map(item => <div className="network-project" key={item.project.id}><div className="network-project-title"><span><b>{item.project.name}</b><small>{item.project.external_key} · площадка {item.project.default_platform_fee_percent}% · {item.project.is_active ? "проект включён" : "проект выключен"}</small></span><em>{item.provider_routes.filter(route => route.is_available).length}/{item.provider_routes.length} готовы</em></div><div className="network-grid network-head"><span>Подключение</span><span>Сумма / диапазон</span><span>День</span><span>Неделя</span><span>Экономика за день</span><span>Нагрузка</span><span>Статус</span><span/></div>{item.provider_routes.length ? item.provider_routes.map(route => { const max = Number(route.daily_amount_limit || 0); const percent = max ? Math.min(100, Math.round(Number(route.daily_used_amount || 0) / max * 100)) : 0; return <div className="network-grid" key={route.id}><span><b>{route.provider_name}</b><small>{route.name} · вес {route.weight} · prio {route.priority}</small></span><span>{route.min_amount ?? "—"} — {route.max_amount ?? "—"}<small>окно {route.available_from && route.available_to ? `${route.available_from.slice(0,5)}—${route.available_to.slice(0,5)}` : "24/7"}</small></span><span>{money(route.daily_used_amount)} / {route.daily_amount_limit ? money(route.daily_amount_limit) : "∞"}<small>{route.daily_used_transactions} операций</small></span><span>{money(route.weekly_used_amount)} / {route.weekly_amount_limit ? money(route.weekly_amount_limit) : "∞"}<small>прибыль {money(route.weekly_profit)}</small></span><span><b className={Number(route.daily_profit) >= 0 ? "profit-positive" : "profit-negative"}>{money(route.daily_profit)}</b><small>площадка {route.platform_fee_percent}% − провайдер {route.provider_fee_percent}%</small></span><span><i className="load-bar"><i style={{ width:`${percent}%` }}/></i><small>{max ? `${percent}% лимита` : "без лимита"}</small></span><span><i className={`tag ${route.is_available ? "succeeded" : "failed"}`}>{route.is_available ? "Готов" : route.unavailable_reason || "Выключен"}</i></span><button className="route-switch" onClick={() => toggleRoute(route)}>{route.is_active ? "Выключить" : "Включить"}</button></div>; }) : <Empty text="Подключений нет."/>}</div>) : <Empty text="Нет проектов для аналитики."/>}</article></section>;
}

function routeLimitsForm(route) {
  return {
    name: route.name || "Основной маршрут",
    priority: route.priority ?? 100,
    weight: route.weight ?? 100,
    min_amount: route.min_amount ?? "",
    max_amount: route.max_amount ?? "",
    daily_amount_limit: route.daily_amount_limit ?? "",
    weekly_amount_limit: route.weekly_amount_limit ?? "",
    daily_transactions_limit: route.daily_transactions_limit ?? "",
    weekly_transactions_limit: route.weekly_transactions_limit ?? "",
    max_transactions_10m: route.max_transactions_10m ?? "",
    max_transactions_hour: route.max_transactions_hour ?? "",
    max_pending_transactions: route.max_pending_transactions ?? "",
    available_from: route.available_from ? route.available_from.slice(0, 5) : "",
    available_to: route.available_to ? route.available_to.slice(0, 5) : "",
    is_active: route.is_active,
  };
}

const numberOrNull = value => value === "" || value === null ? null : Number(value);

function RouteLimitsDialog({ route, projectName, onClose, onSaved }) {
  const [form, setForm] = useState(() => routeLimitsForm(route));
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(routeLimitsForm(route)), [route]);
  const set = key => event => setForm(current => ({
    ...current,
    [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value,
  }));
  const submit = async event => {
    event.preventDefault();
    setBusy(true);
    try {
      await api(`/provider-routes/${route.id}`, {
        method: "PUT",
        body: JSON.stringify({
          name: form.name,
          priority: Number(form.priority),
          weight: Number(form.weight),
          min_amount: numberOrNull(form.min_amount),
          max_amount: numberOrNull(form.max_amount),
          daily_amount_limit: numberOrNull(form.daily_amount_limit),
          weekly_amount_limit: numberOrNull(form.weekly_amount_limit),
          daily_transactions_limit: numberOrNull(form.daily_transactions_limit),
          weekly_transactions_limit: numberOrNull(form.weekly_transactions_limit),
          max_transactions_10m: numberOrNull(form.max_transactions_10m),
          max_transactions_hour: numberOrNull(form.max_transactions_hour),
          max_pending_transactions: numberOrNull(form.max_pending_transactions),
          available_from: form.available_from || null,
          available_to: form.available_to || null,
          is_active: form.is_active,
        }),
      });
      await onSaved();
      onClose();
    } catch (error) {
      onSaved(error.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="route-modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <article className="route-modal card" role="dialog" aria-modal="true" aria-labelledby="route-limits-title">
      <header><div><small>ПЛАТЁЖКА В ПРОЕКТЕ</small><h2 id="route-limits-title">{route.provider_name}</h2><p>{projectName} · {route.name}</p></div><button type="button" className="route-modal-close" onClick={onClose} aria-label="Закрыть">×</button></header>
      <form onSubmit={submit}>
        <div className="route-form-section"><h3>Сумма и приоритет</h3><div className="route-form-grid">
          <label>Название маршрута<input required value={form.name} onChange={set("name")}/></label>
          <label>Приоритет<input type="number" min="0" max="100000" value={form.priority} onChange={set("priority")}/></label>
          <label>Вес распределения<input type="number" min="1" max="100000" value={form.weight} onChange={set("weight")}/></label>
          <label>Минимальная сумма, ₽<input type="number" min="0" step="0.01" placeholder="Без минимума" value={form.min_amount} onChange={set("min_amount")}/></label>
          <label>Максимальная сумма, ₽<input type="number" min="0.01" step="0.01" placeholder="Без максимума" value={form.max_amount} onChange={set("max_amount")}/></label>
        </div></div>
        <div className="route-form-section"><h3>Лимиты по этой платёжке</h3><div className="route-form-grid">
          <label>Сумма в день, ₽<input type="number" min="0.01" step="0.01" placeholder="Без лимита" value={form.daily_amount_limit} onChange={set("daily_amount_limit")}/></label>
          <label>Успешных платежей в день<input type="number" min="1" step="1" placeholder="Без лимита" value={form.daily_transactions_limit} onChange={set("daily_transactions_limit")}/></label>
          <label>Сумма в неделю, ₽<input type="number" min="0.01" step="0.01" placeholder="Без лимита" value={form.weekly_amount_limit} onChange={set("weekly_amount_limit")}/></label>
          <label>Успешных в неделю<input type="number" min="1" step="1" placeholder="Без лимита" value={form.weekly_transactions_limit} onChange={set("weekly_transactions_limit")}/></label>
          <label>Успешных за 10 минут<input type="number" min="1" step="1" placeholder="Без лимита" value={form.max_transactions_10m} onChange={set("max_transactions_10m")}/></label>
          <label>Успешных за час<input type="number" min="1" step="1" placeholder="Без лимита" value={form.max_transactions_hour} onChange={set("max_transactions_hour")}/></label>
          <label>Одновременно в ожидании<input type="number" min="1" step="1" placeholder="Без лимита" value={form.max_pending_transactions} onChange={set("max_pending_transactions")}/></label>
        </div></div>
        <div className="route-form-section"><h3>Время работы</h3><div className="route-form-grid route-time-grid">
          <label>С<input type="time" value={form.available_from} onChange={set("available_from")}/></label>
          <label>До<input type="time" value={form.available_to} onChange={set("available_to")}/></label>
        </div><small className="route-hint">Оба поля пустые — платёжка доступна круглосуточно. Время считается по Москве.</small></div>
        <label className="toggle route-enabled"><input type="checkbox" checked={form.is_active} onChange={set("is_active")}/><i/>Маршрут включён и участвует в выборе платёжки</label>
        <footer><small>Пустое поле означает, что лимита нет. Уже созданные платежи не меняются.</small><span><button type="button" onClick={onClose}>Отмена</button><button className="primary" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить лимиты"}</button></span></footer>
      </form>
    </article>
  </div>;
}

function OperationsDashboard() {
  const { notice } = usePanel();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const reload = async () => { setLoading(true); try { setItems(await api("/analytics/projects")); } catch (error) { notice(error.message); } finally { setLoading(false); } };
  useEffect(() => { reload(); }, []);
  const toggleRoute = async route => { try { await api(`/provider-routes/${route.id}/activation`, { method:"PATCH", body:JSON.stringify({ is_active:!route.is_active }) }); await reload(); notice(`Маршрут ${route.is_active ? "выключен" : "включён"}`); } catch (error) { notice(error.message); } };
  const routes = items.flatMap(item => item.provider_routes);
  const active = routes.filter(route => route.is_active);
  const used = routes.reduce((sum, route) => sum + Number(route.daily_used_amount || 0), 0);
  const capacity = routes.reduce((sum, route) => sum + Number(route.daily_amount_limit || 0), 0);
  const profit = routes.reduce((sum, route) => sum + Number(route.daily_profit || 0), 0);
  const allTimeProfit = routes.reduce((sum, route) => sum + Number(route.all_time_profit || 0), 0);
  const ready = routes.filter(route => route.is_available).length;
  if (loading) return <section><PageHeader title="Операционный центр" text="Загружаем маршруты, лимиты и загрузку…"/><Empty text="Загрузка…"/></section>;
  return <section className="operations-page">
    <PageHeader title="Операционный центр" text="Лимиты считают успешные оплаты; незавершённые заявки защищаются отдельной очередью." action={<button onClick={reload}>↻ Обновить</button>}/>
    <div className="network-kpis six">
      <Metric label="ПРОЕКТЫ" value={items.length} suffix="всего контуров" color="blue"/>
      <Metric label="МАРШРУТЫ" value={active.length} suffix={`${ready} доступны сейчас`} color="green"/>
      <Metric label="ОБОРОТ ЗА ДЕНЬ" value={money(used)} suffix="только успешные" color="violet"/>
      <Metric label="ПРИБЫЛЬ ЗА ДЕНЬ" value={money(profit)} suffix="только успешные" color="green"/>
      <Metric label="ПРИБЫЛЬ ЗА ВСЁ ВРЕМЯ" value={money(allTimeProfit)} suffix="по текущим ставкам" color="blue"/>
      <Metric label="ДНЕВНАЯ ЁМКОСТЬ" value={capacity ? money(capacity) : "∞"} suffix="заданные лимиты" color="orange"/>
    </div>
    <article className="card network-board">
      <div className="network-board-head"><div><small>СЕТЬ ПОДКЛЮЧЕНИЙ</small><h3>Маршруты, лимиты и экономика по проектам</h3></div><span className="live-dot">● live из PostgreSQL</span></div>
      {items.length ? items.map(item => <div className="network-project" key={item.project.id}>
        <div className="network-project-title"><span><b>{item.project.name}</b><small>{item.project.external_key} · площадка {item.project.default_platform_fee_percent}% · {item.project.is_active ? "проект включён" : "проект выключен"}</small></span><em>{item.provider_routes.filter(route => route.is_available).length}/{item.provider_routes.length} готовы</em></div>
        <div className="network-grid network-head"><span>Подключение</span><span>Сумма / диапазон</span><span>День</span><span>Неделя</span><span>Экономика</span><span>Нагрузка</span><span>Статус</span><span>Действия</span></div>
        {item.provider_routes.length ? item.provider_routes.map(route => {
          const max = Number(route.daily_amount_limit || 0);
          const percent = max ? Math.min(100, Math.round(Number(route.daily_used_amount || 0) / max * 100)) : 0;
          return <div className="network-grid" key={route.id}>
            <span><b>{route.provider_name}</b><small>{route.name} · вес {route.weight} · prio {route.priority}</small></span>
            <span>{route.min_amount ?? "—"} — {route.max_amount ?? "—"}<small>окно {route.available_from && route.available_to ? `${route.available_from.slice(0,5)}—${route.available_to.slice(0,5)}` : "24/7"}</small></span>
            <span>{money(route.daily_used_amount)} / {route.daily_amount_limit ? money(route.daily_amount_limit) : "∞"}<small>{route.daily_used_transactions} / {route.daily_transactions_limit ?? "∞"} успешных</small></span>
            <span>{money(route.weekly_used_amount)} / {route.weekly_amount_limit ? money(route.weekly_amount_limit) : "∞"}<small>{route.weekly_used_transactions} / {route.weekly_transactions_limit ?? "∞"} успешных</small></span>
            <span><b className={Number(route.daily_profit) >= 0 ? "profit-positive" : "profit-negative"}>{money(route.daily_profit)}</b><small>за всё время: {money(route.all_time_profit)} · {route.all_time_used_transactions} успешных</small></span>
            <span><i className="load-bar"><i style={{ width:`${percent}%` }}/></i><small>успешно: 10м {route.ten_minute_used_transactions}/{route.max_transactions_10m ?? "∞"} · час {route.hourly_used_transactions}/{route.max_transactions_hour ?? "∞"}<br/>ожидают {route.pending_transactions}/{route.max_pending_transactions ?? "∞"}</small></span>
            <span><i className={`tag ${route.is_available ? "succeeded" : "failed"}`}>{route.is_available ? "Готов" : route.unavailable_reason || "Выключен"}</i></span>
            <span className="network-actions"><button className="route-limits-button" onClick={() => setEditing({ route, projectName:item.project.name })}>Лимиты</button><button className="route-switch" onClick={() => toggleRoute(route)}>{route.is_active ? "Выключить" : "Включить"}</button></span>
          </div>;
        }) : <Empty text="Подключений нет."/>}
      </div>) : <Empty text="Нет проектов для аналитики."/>}
    </article>
    {editing && <RouteLimitsDialog route={editing.route} projectName={editing.projectName} onClose={() => setEditing(null)} onSaved={async error => { if (error) { notice(error); return; } await reload(); notice("Лимиты платёжки сохранены"); }}/>}
  </section>;
}

function UserEditor({ user, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({ full_name:"", email:"", phone:"", telegram_username:"", business_name:"", is_active:true, ...user }));
  const [busy, setBusy] = useState(false);
  const set = key => event => setForm(current => ({ ...current, [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value }));
  const submit = async event => { event.preventDefault(); setBusy(true); try { const payload = { ...form, phone:form.phone || null, telegram_username:form.telegram_username || null }; await api(user?.id ? `/users/${user.id}` : "/users", { method:user?.id ? "PATCH" : "POST", body:JSON.stringify(payload) }); await onSaved(); onClose(); } finally { setBusy(false); } };
  return <div className="route-modal-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><article className="route-modal user-editor card" role="dialog" aria-modal="true"><header><div><small>КАРТОЧКА ПОЛЬЗОВАТЕЛЯ</small><h2>{user?.id ? "Изменить пользователя" : "Новый пользователь"}</h2><p>{user?.id ? "Email используется при создании платежа у MulenPay." : "Заполните данные покупателя."}</p></div><button type="button" className="route-modal-close" onClick={onClose}>×</button></header><form onSubmit={submit}><div className="route-form-grid"><label>Имя<input required value={form.full_name} onChange={set("full_name")}/></label><label>Email<input required type="email" value={form.email || ""} onChange={set("email")}/></label><label>Компания<input required value={form.business_name} onChange={set("business_name")}/></label><label>Телефон<input value={form.phone || ""} onChange={set("phone")}/></label><label>Telegram<input value={form.telegram_username || ""} onChange={set("telegram_username")}/></label></div><label className="toggle route-enabled"><input type="checkbox" checked={form.is_active} onChange={set("is_active")}/><i/>Активен: может выбираться для нового платежа</label><footer><small>ID и история платежей сохраняются при редактировании.</small><span><button type="button" onClick={onClose}>Отмена</button><button className="primary" disabled={busy}>{busy ? "Сохраняем…" : "Сохранить"}</button></span></footer></form></article></div>;
}

function Users() {
  const { notice } = usePanel();
  const [data, setData] = useState({ items:[], total:0, page:1, page_size:50, pages:1 });
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(50); const [query, setQuery] = useState(""); const [loading, setLoading] = useState(true); const [editing, setEditing] = useState(null); const [creating, setCreating] = useState(false); const [importing, setImporting] = useState(false);
  const reload = async () => { setLoading(true); try { const params = new URLSearchParams({ page:String(page), page_size:String(pageSize) }); if (query.trim()) params.set("query", query.trim()); const result = await api(`/users?${params}`); setData(result); if (result.pages < page) setPage(result.pages); } catch (error) { notice(error.message); } finally { setLoading(false); } };
  useEffect(() => { const timer = setTimeout(reload, query ? 250 : 0); return () => clearTimeout(timer); }, [page, pageSize, query]);
  const importFile = async event => { const file = event.target.files?.[0]; event.target.value = ""; if (!file) return; const source = await file.text(); const emails = [...new Set((source.match(/[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}/gi) || []).map(email => email.toLowerCase()))]; if (!emails.length) return notice("В файле не найдены email-адреса"); setImporting(true); try { let created = 0; let skipped = 0; for (let start = 0; start < emails.length; start += 5000) { const result = await api("/users/import", { method:"POST", body:JSON.stringify({ emails:emails.slice(start, start + 5000), full_name_prefix:"Покупатель", business_name:"Импортированный покупатель", start_index:start + 1 }) }); created += result.created; skipped += result.skipped; } setPage(1); await reload(); notice(`Импорт завершён: ${created} добавлено, ${skipped} пропущено`); } catch (error) { notice(error.message); } finally { setImporting(false); } };
  const saved = async () => { await reload(); notice("Пользователь сохранён"); };
  return <section className="users-page"><PageHeader title="Пользователи" text={`${data.total.toLocaleString("ru-RU")} в базе · именно активные пользователи с email участвуют в подборе для оплаты.`} action={<span className="user-actions"><label className="route-limits-button import-button"><input type="file" accept=".txt,.csv,text/plain,text/csv" onChange={importFile}/>{importing ? "Импортируем…" : "Импорт email"}</label><button className="primary" onClick={() => setCreating(true)}>+ Пользователь</button></span>}/><article className="card user-table"><div className="user-toolbar"><input value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} placeholder="Имя, email, компания, телефон или Telegram"/><select value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setPage(1); }}><option value="50">50 на странице</option><option value="100">100 на странице</option><option value="200">200 на странице</option></select></div><div className="users-grid users-head"><span>Пользователь</span><span>Email</span><span>Контакты</span><span>Создан</span><span>Статус</span><span/></div>{loading ? <Empty text="Загружаем пользователей…"/> : data.items.length ? data.items.map(user => <div className="users-grid" key={user.id}><span><b>{user.full_name}</b><small>{user.business_name}</small></span><span className="user-email">{user.email || "—"}</span><span><small>{user.phone || "Телефон не указан"}<br/>{user.telegram_username ? `@${user.telegram_username}` : "Telegram не указан"}</small></span><span><small>{timeLabel(user.registered_at)}</small></span><span><i className={`tag ${user.is_active ? "succeeded" : "failed"}`}>{user.is_active ? "Активен" : "Выключен"}</i></span><button className="route-switch" onClick={() => setEditing(user)}>Открыть</button></div>) : <Empty text="Пользователи не найдены."/>}<footer className="users-pagination"><small>Страница {data.page} из {data.pages}</small><span><button disabled={page <= 1} onClick={() => setPage(current => current - 1)}>← Назад</button><button disabled={page >= data.pages} onClick={() => setPage(current => current + 1)}>Вперёд →</button></span></footer></article>{editing && <UserEditor user={editing} onClose={() => setEditing(null)} onSaved={saved}/>} {creating && <UserEditor onClose={() => setCreating(false)} onSaved={saved}/>}</section>;
}

Analytics = OperationsDashboard;
export default App;
