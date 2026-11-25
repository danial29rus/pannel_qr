import { useEffect, useState } from "react";
import { api } from "./api";
import "./partner-api-guide.css";

export default function PartnerApiGuide({ project }) {
  const [config, setConfig] = useState({ callback_url: "", auth_token: "", secret_key: "" });
  const [revealed, setRevealed] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    setConfig({ callback_url: project?.external_callback_url || "", auth_token: "", secret_key: "" });
    setRevealed(null);
    setMessage("");
  }, [project?.id]);
  if (!project) return null;
  const base = window.location.origin;
  const createUrl = `${base}/api/v1/external/${encodeURIComponent(project.external_key)}/payments`;
  const statusUrl = `${createUrl}/{transaction_id}`;
  const copy = async (value) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      window.prompt("Скопируйте URL", value);
    }
  };
  const generateKey = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) => byte.toString(16).padStart(2, "0")).join("");
  const generatePair = () => {
    setConfig((previous) => ({ ...previous, auth_token: generateKey(), secret_key: generateKey() }));
    setRevealed(null);
  };
  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      await api(`/projects/${project.id}/external-platform`, {
        method: "PUT",
        body: JSON.stringify({
          external_callback_url: config.callback_url || null,
          external_incoming_token: config.auth_token,
          external_callback_secret: config.secret_key,
          status_check_interval_seconds: Number(project.status_check_interval_seconds ?? 30),
          payment_expiry_minutes: Number(project.payment_expiry_minutes ?? 30),
        }),
      });
      setRevealed({ auth_token: config.auth_token, secret_key: config.secret_key });
      setConfig((previous) => ({ ...previous, auth_token: "", secret_key: "" }));
      setMessage("Ключи сохранены. Скопируйте и передайте их партнёру сейчас: повторно панель их не покажет.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setSaving(false);
    }
  };

  return <article className="card partner-api-guide">
    <h3>Реквизиты интеграции партнёра</h3>
    <p>Партнёру выдаются только входной Auth token и Secret key этого проекта. API token провайдера Витрина остаётся в настройках подключения.</p>
    <form className="partner-api-credentials" onSubmit={save}>
      <label>Callback URL <small>необязательно, если партнёр проверяет статусы запросом</small><input type="url" placeholder="https://merchant.example/callback" value={config.callback_url} onChange={(event) => setConfig((previous) => ({ ...previous, callback_url: event.target.value }))}/></label>
      {!revealed && <div className="partner-api-key-actions"><button type="button" onClick={generatePair}>Сгенерировать два ключа</button><button className="primary" disabled={saving || config.auth_token.length < 16 || config.secret_key.length < 16}>{saving ? "Сохраняем…" : "Сохранить ключи"}</button></div>}
      {revealed && <div className="partner-api-revealed"><label>Auth token<input readOnly type="password" value={revealed.auth_token}/><button type="button" onClick={() => copy(revealed.auth_token)}>Копировать Auth token</button></label><label>Secret key<input readOnly type="password" value={revealed.secret_key}/><button type="button" onClick={() => copy(revealed.secret_key)}>Копировать Secret key</button></label><button type="button" onClick={generatePair}>Сгенерировать новую пару</button></div>}
      {message && <p className="partner-api-message">{message}</p>}
    </form>
    <div className="partner-api-endpoint">
      <div><small>Создание платежа</small><code>{createUrl}</code></div>
      <button type="button" onClick={() => copy(createUrl)}>Копировать URL</button>
    </div>
    <div className="partner-api-endpoint">
      <div><small>Проверка статуса</small><code>{statusUrl}</code></div>
      <button type="button" onClick={() => copy(statusUrl)}>Копировать URL</button>
    </div>
    <p>Auth token передаётся в <code>X-Platform-Token</code> (также принимается Bearer). Secret key используется для HMAC подписи запроса в <code>X-Platform-Signature</code>; требуется Unix timestamp в <code>X-Platform-Timestamp</code>. Подпись считается от строки:</p>
    <pre><code>timestamp + "." + METHOD + "." + PATH + "." + sha256(raw_body).hexdigest()</code></pre>
    <p>Для GET статусного запроса тело пустое. Платёжный ID должен быть UUID. Повтор создания с тем же UUID и суммой безопасен; другой email из пула не будет выбран.</p>
  </article>;
}
