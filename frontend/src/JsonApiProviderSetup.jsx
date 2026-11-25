import { useState } from "react";
import { api } from "./api";
import "./json-api-provider.css";

const VITRINA_PRESET = {
  base_url: "https://vitrina-studio.ru",
  create_path: "/api/v1/external/payments",
  status_path: "/api/v1/external/payments/{transaction_id}",
  request_template: {
    transaction_id: "{{transaction_id}}",
    email: "{{email}}",
    amount_rub: "{{amount_rub}}",
  },
  response_paths: {
    id: "transaction_id",
    request_id: "transaction_id",
    status: "status",
    amount: "amount_rub",
    payment_url: "payment_url",
    qr_url: "qr_url",
  },
  status_map: {
    pending: "pending",
    succeeded: "succeeded",
    failed: "failed",
    canceled: "cancelled",
  },
};

const emptyForm = () => ({
  code: "vitrina-api",
  name: "Витрина · внешний API",
  base_url: VITRINA_PRESET.base_url,
  create_path: VITRINA_PRESET.create_path,
  status_path: VITRINA_PRESET.status_path,
  api_token: "",
  auth_header: "Authorization",
  auth_scheme: "Bearer",
  secret_key: "",
  signature_header: "",
  timestamp_header: "",
  currency: "RUB",
  amount_mode: "integer_major",
  request_template: JSON.stringify(VITRINA_PRESET.request_template, null, 2),
  response_paths: JSON.stringify(VITRINA_PRESET.response_paths, null, 2),
  status_map: JSON.stringify(VITRINA_PRESET.status_map, null, 2),
  provider_fee_percent: "0",
});

function parseObject(value, name) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${name}: укажите корректный JSON`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${name}: ожидается JSON-объект`);
  }
  return parsed;
}

export default function JsonApiProviderSetup({ projectId, notice, onCreated }) {
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [savedProvider, setSavedProvider] = useState(null);
  const set = (key) => (event) => setForm((previous) => ({ ...previous, [key]: event.target.value }));

  const useVitrinaPreset = () => setForm((previous) => ({
    ...previous,
    ...emptyForm(),
    api_token: previous.api_token,
    provider_fee_percent: previous.provider_fee_percent,
  }));

  const create = async (event) => {
    event.preventDefault();
    if (!projectId) return notice("Сначала выберите проект в верхней панели");
    setBusy(true);
    try {
      const settings = {
        base_url: form.base_url,
        create_path: form.create_path,
        status_path: form.status_path,
        auth_header: form.auth_header,
        auth_scheme: form.auth_scheme,
        signature_header: form.signature_header,
        timestamp_header: form.timestamp_header,
        currency: form.currency,
        amount_mode: form.amount_mode,
        request_template: parseObject(form.request_template, "Шаблон запроса"),
        response_paths: parseObject(form.response_paths, "Поля ответа"),
        status_map: parseObject(form.status_map, "Статусы"),
      };
      const credentials_encrypted = {
        api_token: form.api_token,
        secret_key: form.secret_key,
      };
      const provider = savedProvider || await api("/providers", {
        method: "POST",
        body: JSON.stringify({
          code: form.code,
          name: form.name,
          adapter_type: "json_api",
          settings,
          credentials_encrypted,
          provider_fee_percent: Number(form.provider_fee_percent || 0),
        }),
      });
      setSavedProvider(provider);
      await api(`/projects/${projectId}/provider-routes`, {
        method: "POST",
        body: JSON.stringify({ provider_id: provider.id, name: `${provider.name} · основной`, priority: 100, weight: 100 }),
      });
      setSavedProvider(null);
      setForm(emptyForm());
      onCreated?.();
      notice("JSON API подключён к выбранному проекту");
    } catch (error) {
      notice(error.message);
    } finally {
      setBusy(false);
    }
  };

  return <article className="card json-api-setup">
    <div className="json-api-heading">
      <div>
        <h3>Универсальное JSON API</h3>
        <p>Настройте endpoint создания, проверки статуса и сопоставление полей без отдельного адаптера под провайдера.</p>
      </div>
      <button type="button" onClick={useVitrinaPreset}>Заполнить Витрину</button>
    </div>
    <form onSubmit={create} className="json-api-fields">
      <label>Название<input required value={form.name} onChange={set("name")}/></label>
      <label>Системный код<input required pattern="[a-z0-9_-]+" value={form.code} onChange={set("code")}/></label>
      <label>API URL<input required type="url" value={form.base_url} onChange={set("base_url")}/></label>
      <label>Путь создания<input required value={form.create_path} onChange={set("create_path")}/></label>
      <label>Путь статуса<input required value={form.status_path} onChange={set("status_path")}/><small>Для ID используйте {"{transaction_id}"}.</small></label>
      <label>Auth token<input type="password" autoComplete="new-password" value={form.api_token} onChange={set("api_token")}/><small>Для Витрины обязателен.</small></label>
      <label>Auth header<input value={form.auth_header} onChange={set("auth_header")}/></label>
      <label>Auth scheme<input value={form.auth_scheme} onChange={set("auth_scheme")}/><small>Для Bearer оставьте `Bearer`.</small></label>
      <label>Secret key <small>необязательно</small><input type="password" autoComplete="new-password" value={form.secret_key} onChange={set("secret_key")}/></label>
      <label>Signature header<input value={form.signature_header} onChange={set("signature_header")}/></label>
      <label>Timestamp header<input value={form.timestamp_header} onChange={set("timestamp_header")}/></label>
      <label>Валюта<input required value={form.currency} onChange={set("currency")}/></label>
      <label>Формат суммы<select value={form.amount_mode} onChange={set("amount_mode")}><option value="integer_major">Целые единицы (amount_rub)</option><option value="decimal_major">Десятичные единицы</option></select></label>
      <label>Комиссия провайдера, %<input type="number" min="0" max="100" step="0.01" value={form.provider_fee_percent} onChange={set("provider_fee_percent")}/></label>
      <label className="json-editor">Шаблон JSON создания<textarea required rows="7" spellCheck="false" value={form.request_template} onChange={set("request_template")}/></label>
      <label className="json-editor">Пути полей ответа<textarea required rows="7" spellCheck="false" value={form.response_paths} onChange={set("response_paths")}/></label>
      <label className="json-editor">Сопоставление статусов<textarea required rows="6" spellCheck="false" value={form.status_map} onChange={set("status_map")}/></label>
      <div className="json-api-actions"><button className="primary" disabled={busy}>{busy ? "Подключаем…" : "Создать и подключить к проекту"}</button></div>
    </form>
    <p className="json-api-note">Шаблон поддерживает переменные: <code>{"{{transaction_id}}"}</code>, <code>{"{{email}}"}</code>, <code>{"{{amount}}"}</code>, <code>{"{{amount_rub}}"}</code>, <code>{"{{currency}}"}</code>, <code>{"{{description}}"}</code>, <code>{"{{api_token}}"}</code>, <code>{"{{secret_key}}"}</code>. Если указаны Signature/Timestamp headers, adapter рассчитывает lowercase hex HMAC-SHA256 от <code>timestamp + "." + raw JSON body</code>. Для Витрины используйте отдельный API token из <code>PAYMENTS_API_TOKENS</code>; Secret key там не нужен.</p>
  </article>;
}
