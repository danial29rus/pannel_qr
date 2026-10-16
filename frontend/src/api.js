const root = "/api/v1";
export const PANEL_AUTH_EXPIRED = "panel-auth-expired";
export const api = async (path, options = {}) => {
  const token = sessionStorage.getItem("panel-token");
  const response = await fetch(`${root}${path}`, { ...options, headers: { "Content-Type": "application/json", ...(token ? { "X-Panel-Token": token } : {}), ...options.headers } });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && token && path !== "/auth/login") {
      sessionStorage.removeItem("panel-token");
      window.dispatchEvent(new Event(PANEL_AUTH_EXPIRED));
      throw new Error("Сессия завершена. Войдите снова.");
    }
    throw new Error(typeof data.detail === "string" ? data.detail : "Операция отклонена сервером");
  }
  return response.status === 204 ? null : response.json();
};
export const money = (n) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(Number(n || 0));
