// Message check: paste a message; see the scam it matches, the words that gave it away, and every link checked.
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router";
import { api } from "../api";
import { LinkScan } from "../components/LinkScan";
import { useT } from "../i18n";
import { highlight, overallLevel, type Level, type MessageResult } from "../messages";
import { StatusTag } from "../components/ui";

const MAX = 2000;
const TAG: Record<Level, string> = { danger: "bad", caution: "warn", clear: "done" };

export function MessagePage() {
  const given = (useLocation().state as { text?: string } | null)?.text ?? "";
  const [text, setText] = useState(given.slice(0, MAX));
  const [checked, setChecked] = useState("");
  const [result, setResult] = useState<MessageResult | null>(null);
  const [links, setLinks] = useState<Record<string, Level>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const t = useT();
  const results = useRef<HTMLDivElement>(null);

  async function check(value: string) {
    if (!value.trim()) { setError(t("Paste a message to check.")); return; }
    setBusy(true);
    setError("");
    setResult(null);
    setLinks({});
    try {
      const found = await api<MessageResult>("/api/messages", { method: "POST", body: { text: value } });
      setChecked(value);
      setResult(found);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { if (given.trim()) void check(given.slice(0, MAX)); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // On a phone the result sits below the message box, out of sight.
  useEffect(() => {
    if (result && matchMedia("(max-width: 900px)").matches) results.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [result]);

  const noteLink = useCallback((value: string, level: Level) => setLinks((l) => ({ ...l, [value]: level })), []);
  const submit = (event: FormEvent) => { event.preventDefault(); void check(text); };

  const linkItems = result?.items.filter((i) => i.kind === "link") ?? [];
  const level = result ? overallLevel(result.level, Object.values(links)) : "clear";
  const raisedByLink = result && level !== result.level;
  const scanning = linkItems.length > Object.keys(links).length;

  return (
    <section>
      <div className="tool-head">
        <h1 className="small-h1">{t("Paste a message you're not sure about.")}</h1>
      </div>
      <div className={result ? "tool-split" : "tool-single"}>
        <form onSubmit={submit}>
          <textarea className="input message-box" aria-label={t("Message to check")} maxLength={MAX} value={text}
            placeholder={t("Paste the SMS or WhatsApp message here")} onChange={(e) => setText(e.target.value)} />
          <div className="actions">
            <button className="btn btn-primary" type="submit" disabled={busy}>{t(busy ? "Checking" : "Check message")}</button>
            {text.length >= MAX - 200 && <span className="small">{t("{count} of {max} characters", { count: text.length, max: MAX })}</span>}
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <p className="note small">{t("Messages aren't stored. Links in them are opened in a sealed browser, so a one-time link may stop working.")}</p>
        </form>

        <div aria-live="polite" ref={results}>
          {result && (
            <div className="stack">
              <section className={`card level-${level === "clear" ? "clear" : level}`}>
                <div className="verdict-line"><StatusTag status={TAG[level]} /></div>
                <h3>{t(raisedByLink && level === "danger" ? "A link in this message looks dangerous"
                  : raisedByLink ? "A link in this message needs care" : result.verdict)}</h3>
                <p className="sub">{t(raisedByLink ? "See the link check below before you open it." : result.summary)}</p>
                {result.matches.length > 0 && (
                  <p className="quoted">{highlight(checked, result.matches).map((part, i) =>
                    part.marked ? <mark key={i}>{part.text}</mark> : <span key={i}>{part.text}</span>)}</p>
                )}
                {result.scripts.length > 1 && (
                  <ul className="signals">{result.scripts.slice(1).map((s) => <li key={s.id} className={s.strength === "strong" ? "red" : "amber"}>
                    <b>{t(s.title)}.</b> {t(s.explanation)}</li>)}</ul>
                )}
              </section>

              {result.items.length > 0 && (
                <section className="card">
                  <h3>{t("In this message")}</h3>
                  <ul className="found-items">
                    {result.items.map((item) => (
                      <li key={`${item.kind}-${item.value}`}>
                        {item.kind === "link" ? <LinkScan target={item.value} onLevel={(l) => noteLink(item.value, l)} />
                          : item.kind === "upi" ? (
                            <div className="link-scan">
                              <div className="link-scan-text"><span className="link-value">{item.value}</span>
                                <span className="small">{item.payment ? t("UPI: {verdict}. Your UPI app shows the registered name before you pay.", { verdict: t(item.payment.verdict) }) : t("This UPI link isn't valid.")}</span></div>
                              <div className="link-scan-side"><StatusTag status={item.payment ? TAG[item.payment.level] : "skipped"} /></div>
                            </div>
                          ) : (
                            <div className="link-scan">
                              <div className="link-scan-text"><span className="link-value">{item.value}</span>
                                <span className="small">{t("Artemis can't tell who owns a number. Use the one on your card or the official site.")}</span></div>
                            </div>
                          )}
                      </li>
                    ))}
                  </ul>
                  {scanning && <p className="small">{t("Still checking links.")}</p>}
                </section>
              )}

              {level !== "clear" && (
                <section className="card">
                  <h3>{t("What to do")}</h3>
                  <p className="sub">{t("Don't click, pay, call back or share any code. If you've already paid or shared details:")}</p>
                  <div className="todo">
                    <a href="tel:1930"><span>{t("Call 1930")}<small>{t("National cyber fraud helpline")}</small></span></a>
                    <a href="https://cybercrime.gov.in/" target="_blank" rel="noopener noreferrer"><span>{t("Report it on cybercrime.gov.in")}</span></a>
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
