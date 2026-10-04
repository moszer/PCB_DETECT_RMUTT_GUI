"use client";

import React, { useEffect, useState } from "react";
import { Bot, CircleCheck, CircleX, ExternalLink, Eye, EyeOff, KeyRound, Save, Trash2, Zap } from "lucide-react";
import type { AIConfig, AIProvider } from "@/types";
import { api } from "@/lib/api";
import { Badge, Button, Card, CardHeader, Field, Segmented, Spinner, TextInput, cx } from "./ui";
import { useToast } from "./Toast";

const PROVIDERS: Record<AIProvider, { label: string; keyUrl: string; placeholder: string; modelsLabel: string; modelsHint: string }> = {
  gemini: {
    label: "Google Gemini",
    keyUrl: "https://aistudio.google.com/apikey",
    placeholder: "AIza… หรือ AQ.…",
    modelsLabel: "โมเดล (เรียงตามลำดับที่จะลอง)",
    modelsHint: "คั่นด้วยจุลภาค เว้นว่าง = ค่าเริ่มต้น · ผู้ช่วย AI ทุกหน้าใช้ Gemini",
  },
  openrouter: {
    label: "OpenRouter",
    keyUrl: "https://openrouter.ai/keys",
    placeholder: "sk-or-v1-…",
    modelsLabel: "โมเดล",
    modelsHint: "เช่น qwen/qwen3.8-27b:free · ใช้ได้กับแชทถามเรื่องบอร์ด (ผู้ช่วย AI ทุกหน้าต้องใช้ Gemini)",
  },
};

/**
 * AI assistant key and provider, saved on the station (backend/.env). The browser never
 * receives a saved key back, only whether it is set and a masked hint.
 */
export function AIKeyPanel({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const [config, setConfig] = useState<AIConfig | null>(null);
  const [tab, setTab] = useState<AIProvider>("gemini");
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [models, setModels] = useState<Record<AIProvider, string>>({ gemini: "", openrouter: "" });
  const [busy, setBusy] = useState<"save" | "test" | "remove" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    api.aiConfig
      .get()
      .then((c) => {
        setConfig(c);
        setTab(c.provider);
        setModels({ gemini: c.providers.gemini.models, openrouter: c.providers.openrouter.models });
      })
      .catch((err) => toast.error("อ่านการตั้งค่า AI ไม่สำเร็จ", err));
  }, [toast]);

  if (!config) {
    return (
      <Card>
        <CardHeader icon={Bot} title="ผู้ช่วย AI" />
        <div className="p-6 grid place-items-center">
          <Spinner />
        </div>
      </Card>
    );
  }

  const info = config.providers[tab];
  const meta = PROVIDERS[tab];
  const lockReason = isOperator ? null : "ขอสิทธิ์ควบคุมก่อน";
  const switchTab = (p: AIProvider) => {
    setTab(p);
    setKey("");
    setResult(null);
  };

  const run = async (kind: "save" | "test" | "remove", task: () => Promise<void>) => {
    setBusy(kind);
    try {
      await task();
    } catch (err) {
      toast.error(kind === "test" ? "ทดสอบไม่สำเร็จ" : "บันทึกไม่สำเร็จ", err);
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run("save", async () => {
      const next = await api.aiConfig.update({
        provider: tab,
        [`${tab}_api_key`]: key.trim() || undefined,
        [tab === "gemini" ? "gemini_models" : "openrouter_model"]: models[tab],
      });
      setConfig(next);
      setKey("");
      setResult(null);
      toast.success("บันทึกการตั้งค่า AI แล้ว", `ใช้ ${PROVIDERS[tab].label} · มีผลทันที ไม่ต้องรีสตาร์ท`);
    });

  const test = () =>
    run("test", async () => {
      setResult(null);
      setResult(await api.aiConfig.test(tab, key.trim() || undefined));
    });

  const remove = () => {
    if (!window.confirm(`ลบ API key ของ ${meta.label} ออกจากสถานี?`)) return;
    run("remove", async () => {
      setConfig(await api.aiConfig.update({ [`${tab}_api_key`]: "" }));
      setResult(null);
      toast.success("ลบ API key แล้ว");
    });
  };

  const active = config.provider === tab;
  return (
    <Card>
      <CardHeader
        icon={Bot}
        title="ผู้ช่วย AI"
        subtitle="API key เก็บในไฟล์ backend/.env บนเครื่องสถานี และไม่ถูกส่งกลับมาที่เบราว์เซอร์"
        actions={
          config.configured ? (
            <Badge tone="pass">
              <CircleCheck className="size-3" /> พร้อมใช้ · {PROVIDERS[config.provider].label}
            </Badge>
          ) : (
            <Badge tone="review">ยังไม่ได้ตั้งค่า</Badge>
          )
        }
      />
      <div className="p-4 flex flex-col gap-4">
        <Segmented
          className="w-full sm:w-auto self-start"
          value={tab}
          onChange={switchTab}
          options={(Object.keys(PROVIDERS) as AIProvider[]).map((p) => ({
            value: p,
            label: (
              <span className="inline-flex items-center gap-1.5">
                {PROVIDERS[p].label}
                {config.provider === p && <span className="size-1.5 rounded-full bg-pass" aria-label="ใช้งานอยู่" />}
              </span>
            ),
          }))}
        />

        <Field
          label="API key"
          hint={info.key_set ? `บันทึกไว้แล้ว: ${info.key_hint} — ใส่ key ใหม่เพื่อแทนที่ หรือเว้นว่างเพื่อใช้ key เดิม` : "ยังไม่มี key ของผู้ให้บริการนี้"}
          aside={
            <a href={meta.keyUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
              ขอ key ฟรี <ExternalLink className="size-3" />
            </a>
          }
        >
          <div className="flex gap-2">
            <div className="relative flex-1 min-w-0">
              <KeyRound className="size-4 text-subtle absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <TextInput
                type={showKey ? "text" : "password"}
                autoComplete="off"
                spellCheck={false}
                className="pl-9 pr-10 font-mono text-sm"
                placeholder={info.key_set ? (info.key_hint ?? "") : meta.placeholder}
                value={key}
                disabled={!isOperator}
                onChange={(e) => {
                  setKey(e.target.value);
                  setResult(null);
                }}
                aria-label={`API key ของ ${meta.label}`}
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                aria-label={showKey ? "ซ่อน key" : "แสดง key"}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 size-8 grid place-items-center rounded text-subtle hover:text-text cursor-pointer"
              >
                {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </div>
        </Field>

        <Field label={meta.modelsLabel} hint={meta.modelsHint}>
          <TextInput
            className="font-mono text-sm"
            placeholder="ค่าเริ่มต้น"
            value={models[tab]}
            disabled={!isOperator}
            onChange={(e) => setModels((m) => ({ ...m, [tab]: e.target.value }))}
          />
        </Field>

        {result && (
          <div
            role="status"
            className={cx(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm animate-rise",
              result.ok ? "bg-pass-soft text-pass" : "bg-fail-soft text-fail"
            )}
          >
            {result.ok ? <CircleCheck className="size-4 shrink-0" /> : <CircleX className="size-4 shrink-0" />}
            {result.message}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            icon={Save}
            loading={busy === "save"}
            disabled={!!busy || !isOperator || (!key.trim() && !info.key_set)}
            reason={lockReason ?? (!key.trim() && !info.key_set ? "ใส่ API key ก่อน" : null)}
            onClick={save}
          >
            {active ? "บันทึก" : `บันทึกและใช้ ${meta.label}`}
          </Button>
          <Button icon={Zap} loading={busy === "test"} disabled={!!busy || !isOperator || (!key.trim() && !info.key_set)} onClick={test}>
            ทดสอบ key
          </Button>
          {info.key_set && (
            <Button variant="ghost" icon={Trash2} loading={busy === "remove"} disabled={!!busy || !isOperator} onClick={remove} className="sm:ml-auto text-fail">
              ลบ key
            </Button>
          )}
        </div>
        {!isOperator && <p className="text-xs text-review">ต้องกด “ขอสิทธิ์ควบคุม” (มุมขวาบน) และใส่รหัสผ่านสถานีก่อน จึงจะแก้ไข API key ได้</p>}
      </div>
    </Card>
  );
}
