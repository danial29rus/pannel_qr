const root = "/api/v1";
export const PANEL_AUTH_EXPIRED = "panel-auth-expired";
export const api = async (path, options = {}) => {
  const token = sessionStorage.getItem("panel-token");
  const timeout = AbortSignal.timeout(30000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  const response = await fetch(`${root}${path}`, { ...options, signal, headers: { "Content-Type": "application/json", ...(token ? { "X-Panel-Token": token } : {}), ...options.headers } });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && token && path !== "/auth/login") {
      sessionStorage.removeItem("panel-token");
      window.dispatchEvent(new Event(PANEL_AUTH_EXPIRED));
      throw new Error("Сессия завершена. Войдите снова.");
    }
    const detail = Array.isArray(data.detail) ? data.detail.map(item => `${item.loc?.slice(1).join(".") || "Поле"}: ${item.msg}`).join("; ") : data.detail;
    throw new Error(typeof detail === "string" ? detail : `Операция отклонена сервером (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
};
export const money = (n) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(n || 0));
