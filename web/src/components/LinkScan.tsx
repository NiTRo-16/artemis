// Scans one link through the normal queue and shows how it's going, for the message and QR checks.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { getScan, startScan } from "../api";
import { translate, useT } from "../i18n";
import { linkLevel, type Level } from "../messages";
import type { Report, ScanEvent } from "../types";
import { StatusTag } from "./ui";

const TOTAL_STEPS = 6;

export function LinkScan({ target, onLevel }: { target: string; onLevel?: (level: Level) => void }) {
  const [id, setId] = useState<string | null>(null);
  const [steps, setSteps] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const t = useT();

  useEffect(() => {
    let stopped = false;
    let events: EventSource | null = null;
    const finish = (found: Report) => {
      if (stopped) return;
      setReport(found);
      onLevel?.(linkLevel(found));
    };
    startScan(target).then(async (started) => {
      if (stopped) return;
      if (started.id === null) { finish(started.report); return; }
      const jobId = started.id;
      setId(jobId);
      if (started.status === "done") {   // scanned recently: the saved result
        const saved = await getScan(jobId);
        if (saved.report) finish(saved.report);
        return;
      }
      events = new EventSource(`/api/scans/${encodeURIComponent(jobId)}/events`);
      events.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as ScanEvent;
        if (event.type === "step") setSteps((n) => n + 1);
        else {
          events?.close();
          if (event.type === "done") finish(event.report);
          else if (!stopped) setError(translate(event.message));
        }
      };
      events.onerror = () => {
        events?.close();
        if (!stopped) setError(translate("Lost the connection to the scan."));
      };
    }).catch((err) => { if (!stopped) setError((err as Error).message); });
    return () => { stopped = true; events?.close(); };
  }, [target]);   // eslint-disable-line react-hooks/exhaustive-deps

  const level = report && linkLevel(report);
  const offline = report && report.resolves === false;
  return (
    <div className="link-scan">
      <div className="link-scan-text">
        <span className="link-value">{target}</span>
        <span className="small">
          {error || (report
            ? (offline ? t("Offline: the address doesn't load.") + " " : "") + t(report.impersonation?.verdict ?? "")
            : t("Checking in a sealed browser, {done} of {total}", { done: steps, total: TOTAL_STEPS }))}
        </span>
      </div>
      <div className="link-scan-side">
        {report && id && <Link className="btn btn-small" to={`/scan/${id}`} state={{ report }}>{t("Full report")}</Link>}
        {error ? <StatusTag status="skipped" />
          : !report ? <StatusTag status="run" />
          : <StatusTag status={level === "danger" ? "bad" : level === "caution" ? "warn" : "done"} />}
      </div>
    </div>
  );
}
