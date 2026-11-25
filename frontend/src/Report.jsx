import { useEffect, useState } from "react";
import { api, money } from "./api";
import { moscowDate, periodRange } from "./periods";

export function PeriodPicker({ kind, setKind, date, setDate }) {
  const range = periodRange(kind, date);
  return <div className="report-period"><div className="period">{[["today", "Сегодня"], ["week", "Эта неделя"], ["previous", "Прошлая неделя"], ["month", "Этот месяц"]].map(([value, title]) => <button type="button" key={value} className={kind === value ? "chosen" : ""} onClick={() => setKind(value)}>{title}</button>)}</div><label>Неделя по дате<input type="date" value={date} onChange={event => { if (event.target.value) { setDate(event.target.value); setKind("selected"); } }}/></label><small>{kind ? `${range.label} · недели Пн–Вс` : "Любой период · выберите неделю или укажите даты вручную"}</small></div>;
}

export default function Report({ projectId, notice }) {
  const [kind, setKind] = useState("week"), [date, setDate] = useState(moscowDate);
  const [data, setData] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const range = periodRange(kind, date);
  useEffect(() => {
    setData(null); setError("");
    if (!projectId) return;
    const controller = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({ project_id:projectId, currency:"RUB", from_date:range.from, to_date:range.to });
    api(`/dashboard/summary?${params}`, { signal:controller.signal }).then(result => { if (!controller.signal.aborted) setData(result); }).catch(e => { if (!controller.signal.aborted) { setError(e.message); notice(e.message); } }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [projectId, range.from, range.to, revision]);
  const daily = data?.daily || [];
  const max = Math.max(...daily.map(day => Number(day.amount)), 1);
  const success = data?.payment_count ? Math.round(data.success_count / data.payment_count * 100) : 0;
  return <article className="card financial-report"><div className="report-heading"><div><h3>Платежи за период</h3><p>Выбранный проект · RUB · по дате создания платежа</p></div><button onClick={() => setRevision(value => value + 1)} disabled={!projectId || loading}>Обновить</button></div><PeriodPicker kind={kind} setKind={setKind} date={date} setDate={setDate}/>{!projectId ? <p className="empty">Выберите проект для просмотра отчёта.</p> : loading ? <p className="empty">Загружаем отчёт…</p> : error ? <p role="alert" className="empty">{error}</p> : data && <><div className="report-totals"><span>Оборот<strong>{money(data.paid_by_clients)} ₽</strong></span><span>Платежей<strong>{data.payment_count}</strong></span><span>Успешных<strong>{success}%</strong></span><span>В ожидании<strong>{data.pending_count}</strong></span><span>Ошибки / отмены / возвраты<strong>{data.failed_count}</strong></span></div>{data.payment_count ? <div className="daily-chart" role="img" aria-label="Оборот успешных платежей по дням"><div className="daily-bars">{daily.map(day => <div className="daily-column" key={day.date}><span className="daily-value">{money(day.amount)}</span><div className="daily-track"><div style={{ height:`${Number(day.amount) / max * 100}%` }} title={`${day.date}: ${money(day.amount)} ₽ · ${day.payment_count} платежей`}/></div><small>{day.date.slice(8)}.{day.date.slice(5,7)}</small></div>)}</div></div> : <p className="empty">За этот период платежей нет.</p>}<small>Оборот учитывает только успешные платежи. Наведите на столбец, чтобы увидеть сумму и число заявок.</small></>}</article>;
}
