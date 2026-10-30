// QR check: read a QR code in the browser (the image is never uploaded), show what it really does, and check it.
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router";
import { startScan } from "../api";
import { LinkScan } from "../components/LinkScan";
import { Icon } from "../components/ui";
import { classifyQr, decodeFile, type QrKind } from "../qr";
import type { Report } from "../types";
import { PaymentCard } from "./ResultPage";

type Read = { text: string; kind: QrKind };

export function QrPage() {
  const [read, setRead] = useState<Read | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLDivElement>(null);

  async function open(file: File | undefined | null) {
    if (!file) return;
    setRead(null);
    setReport(null);
    setError("");
    if (!file.type.startsWith("image/")) { setError("That isn't an image. Choose a PNG, JPG or WebP screenshot."); return; }
    setBusy(true);
    try {
      const text = await decodeFile(file);
      if (!text) { setError("No QR code found. Try a sharper screenshot, or crop it close to the code."); return; }
      const kind = classifyQr(text);
      setRead({ text, kind });
      if (kind === "upi") {
        const started = await startScan(text.trim());
        if (started.id === null) setReport(started.report);
      }
    } catch (err) {
      setError(err instanceof DOMException ? "This image couldn't be opened. Try a PNG or JPG." : (err as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  // Paste a screenshot anywhere on the page.
  useEffect(() => {
    const paste = (e: ClipboardEvent) => {
      const file = [...(e.clipboardData?.files ?? [])].find((f) => f.type.startsWith("image/"));
      if (file) void open(file);
    };
    window.addEventListener("paste", paste);
    return () => window.removeEventListener("paste", paste);
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // On a phone the result sits below the upload box, out of sight.
  useEffect(() => {
    if (read && matchMedia("(max-width: 900px)").matches) results.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [read]);

  function drop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    void open(e.dataTransfer.files[0]);
  }

  return (
    <section>
      <div className="tool-head">
        <h1 className="small-h1">Check a QR code before you pay.</h1>
      </div>
      <div className={read ? "tool-split" : "tool-single"}>
        <div>
          <label className={`dropzone${over ? " over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)} onDrop={drop}>
            <Icon name="qr" className="icon drop-icon" />
            <b>{busy ? "Reading the code" : "Choose a screenshot"}</b>
            <span className="small">or drop or paste it here</span>
            <input ref={input} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" aria-label="QR code screenshot"
              onChange={(e) => void open(e.target.files?.[0])} />
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <p className="note small">The image stays on your device.</p>
        </div>

        <div aria-live="polite" ref={results}>
          {!read ? null : read.kind === "upi" ? (
            <div className="stack">
              <div className="card qr-warning"><b>Scanning a QR and entering your PIN always sends money.</b>
                <p className="sub">You never need your PIN to receive money.</p></div>
              {report?.payment ? <PaymentCard payment={report.payment} /> : !error && <div className="card"><p className="sub">Checking this payment</p></div>}
            </div>
          ) : read.kind === "link" ? (
            <div className="stack">
              <section className="card">
                <h3>This code opens a website</h3>
                <p className="decoded">{read.text}</p>
              </section>
              <section className="card"><h3>Link check</h3><LinkScan target={read.text.trim()} /></section>
            </div>
          ) : (
            <section className="card">
              <h3>This code isn't a link or a payment</h3>
              <p className="decoded">{read.text}</p>
              <div className="actions"><Link className="btn" to="/messages" state={{ text: read.text }}>Check it as a message</Link></div>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
