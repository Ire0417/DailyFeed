import React, { useEffect, useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { api } from "../services/api";

const CHANNEL_OPTIONS = [
  { key: "email", label: "📧 Email", hint: "发送到你的邮箱" },
  { key: "wechat", label: "💬 企业微信", hint: "通过 Webhook 推送到企业微信" },
  { key: "dingtalk", label: "📱 钉钉", hint: "通过 Webhook 推送到钉钉群" },
];

const Settings: React.FC = () => {
  const { user, refresh } = useAuth();
  const [channels, setChannels] = useState<string[]>([]);
  const [emailRecipients, setEmailRecipients] = useState<string>("");
  const [wechatWebhook, setWechatWebhook] = useState<string>("");
  const [dingtalkWebhook, setDingtalkWebhook] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgError, setMsgError] = useState<string | null>(null);

  useEffect(() => {
    if (!user?.id) return;
    const settings = user.settings || {};
    setChannels(settings.channels || ["email"]);
    setEmailRecipients((settings.email_recipients || [user.email || ""]).join(", "));
    setWechatWebhook(settings.wechat_webhook || "");
    setDingtalkWebhook(settings.dingtalk_webhook || "");
  }, [user?.id, user?.email]);

  const toggleChannel = (ch: string) => {
    setChannels((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch]
    );
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    setMsgError(null);
    try {
      const recipients = emailRecipients
        .split(/[,;]/)
        .map((s) => s.trim())
        .filter(Boolean);
      await api.put("/users/me/settings", {
        channels,
        email_recipients: recipients,
        wechat_webhook: wechatWebhook,
        dingtalk_webhook: dingtalkWebhook,
      });
      setMsg("设置已保存 ✅");
      // 刷新本地用户信息
      refresh().catch(() => {});
    } catch (err: any) {
      setMsgError(err?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold">推送设置</h1>
        <p className="text-slate-500 text-sm mt-1">配置报告的推送渠道与接收者。</p>
      </div>

      {/* User info */}
      <div className="bg-white border rounded-2xl p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm text-slate-500">当前用户</div>
            <div className="text-lg font-medium text-slate-900 mt-1">
              {user?.username || "—"}
            </div>
            <div className="text-sm text-slate-500 mt-0.5">{user?.email || ""}</div>
          </div>
          <div className="text-sm text-slate-500">
            登录状态：{user?.isLoggedIn ? "✅ 已登录" : "未登录"}
          </div>
        </div>
      </div>

      {/* Channels */}
      <div className="bg-white border rounded-2xl p-6 space-y-6">
        <div>
          <h2 className="text-lg font-semibold">推送渠道</h2>
          <p className="text-slate-500 text-sm mt-1">勾选你希望接收报告的推送方式。</p>
        </div>

        <div className="space-y-3">
          {CHANNEL_OPTIONS.map((opt) => (
            <label
              key={opt.key}
              className={`flex items-center gap-3 p-4 border rounded-xl cursor-pointer transition ${
                channels.includes(opt.key)
                  ? "border-slate-900 bg-slate-50"
                  : "border-slate-200 hover:border-slate-300"
              }`}
            >
              <input
                type="checkbox"
                checked={channels.includes(opt.key)}
                onChange={() => toggleChannel(opt.key)}
                className="w-4 h-4 text-slate-900 rounded"
              />
              <div className="flex-1">
                <div className="font-medium text-slate-900">{opt.label}</div>
                <div className="text-sm text-slate-500 mt-0.5">{opt.hint}</div>
              </div>
              {channels.includes(opt.key) && (
                <span className="text-xs text-emerald-700 bg-emerald-50 px-2 py-1 rounded">
                  已启用
                </span>
              )}
            </label>
          ))}
        </div>
      </div>

      {/* Email recipients */}
      {channels.includes("email") && (
        <div className="bg-white border rounded-2xl p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">📧 邮箱接收者</h2>
            <p className="text-slate-500 text-sm mt-1">使用逗号或分号分隔多个邮箱地址。</p>
          </div>
          <input
            type="text"
            value={emailRecipients}
            onChange={(e) => setEmailRecipients(e.target.value)}
            placeholder="me@example.com, friend@example.com"
            className="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900 font-mono text-sm"
          />
        </div>
      )}

      {/* WeChat Webhook */}
      {channels.includes("wechat") && (
        <div className="bg-white border rounded-2xl p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">💬 企业微信 Webhook</h2>
            <p className="text-slate-500 text-sm mt-1">
              在企业微信群中添加「群机器人」，把获得的 Webhook URL 粘贴到这里。
            </p>
          </div>
          <input
            type="text"
            value={wechatWebhook}
            onChange={(e) => setWechatWebhook(e.target.value)}
            placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
            className="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900 font-mono text-sm"
          />
        </div>
      )}

      {/* Dingtalk Webhook */}
      {channels.includes("dingtalk") && (
        <div className="bg-white border rounded-2xl p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">📱 钉钉 Webhook</h2>
            <p className="text-slate-500 text-sm mt-1">
              在钉钉群中添加「智能群助手」→「自定义机器人」，将 Webhook URL 粘贴到这里。
            </p>
          </div>
          <input
            type="text"
            value={dingtalkWebhook}
            onChange={(e) => setDingtalkWebhook(e.target.value)}
            placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
            className="w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900 font-mono text-sm"
          />
        </div>
      )}

      {/* Save */}
      <div className="flex items-center justify-between">
        <div className="text-sm">
          {msg ? <span className="text-emerald-600">{msg}</span> : null}
          {msgError ? <span className="text-red-600">{msgError}</span> : null}
        </div>
        <button
          onClick={save}
          disabled={saving}
          className="px-6 py-2.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 transition font-medium"
        >
          {saving ? "保存中..." : "💾 保存设置"}
        </button>
      </div>
    </div>
  );
};

export default Settings;
