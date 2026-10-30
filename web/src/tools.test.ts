// The logic behind the message and QR checks.
import QRCode from "qrcode";
import { describe, expect, it } from "vitest";
import { highlight, linkLevel, overallLevel } from "./messages";
import { classifyQr, decodePixels } from "./qr";
import type { Report } from "./types";

function qrPixels(text: string, scale = 6, margin = 4) {
  const qr = QRCode.create(text, { errorCorrectionLevel: "M" });
  const n = qr.modules.size;
  const size = (n + margin * 2) * scale;
  const data = new Uint8ClampedArray(size * size * 4).fill(255);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      if (!qr.modules.get(y, x)) continue;
      for (let py = 0; py < scale; py++) {
        for (let px = 0; px < scale; px++) {
          const i = (((y + margin) * scale + py) * size + (x + margin) * scale + px) * 4;
          data[i] = data[i + 1] = data[i + 2] = 0;
        }
      }
    }
  }
  return { data, size };
}

describe("reading a QR code", () => {
  it.each([
    "upi://pay?pa=refund.desk@okaxis&pn=SBI%20Refund&am=4999&tn=Refund",
    "https://sbi-kyc-update.example/pan?id=77",
    "Just some plain words",
  ])("decodes %s", (text) => {
    const { data, size } = qrPixels(text);
    expect(decodePixels(data, size, size)).toBe(text);
  });

  it("finds nothing in a blank image", () => {
    expect(decodePixels(new Uint8ClampedArray(200 * 200 * 4).fill(255), 200, 200)).toBeNull();
  });

  it("tells payments, links and other text apart", () => {
    expect(classifyQr("upi://pay?pa=a@ybl")).toBe("upi");
    expect(classifyQr("UPI://PAY?pa=a@ybl")).toBe("upi");
    expect(classifyQr("https://a.example/x")).toBe("link");
    expect(classifyQr("www.a.example")).toBe("link");
    expect(classifyQr("a-site.example.com/x")).toBe("link");
    expect(classifyQr("WIFI:S:home;T:WPA;P:secret;;")).toBe("other");
    expect(classifyQr("tel:+919000000000")).toBe("other");
    expect(classifyQr("javascript:alert(1)")).toBe("other");
    expect(classifyQr("hello there")).toBe("other");
  });
});

describe("highlighting a message", () => {
  it("marks the matched words and keeps the rest", () => {
    expect(highlight("your account is blocked now", [{ start: 16, end: 23, script: "x" }])).toEqual([
      { text: "your account is ", marked: false }, { text: "blocked", marked: true }, { text: " now", marked: false },
    ]);
  });
  it("joins overlapping matches", () => {
    const parts = highlight("abcdefgh", [{ start: 1, end: 4, script: "x" }, { start: 3, end: 6, script: "y" }]);
    expect(parts).toEqual([{ text: "a", marked: false }, { text: "bcdef", marked: true }, { text: "gh", marked: false }]);
  });
  it("returns the text unchanged without matches", () => {
    expect(highlight("hello", [])).toEqual([{ text: "hello", marked: false }]);
  });
});

describe("how a link affects the verdict", () => {
  const report = (level: string, risk = "Low", payment?: string) => ({
    domain: "a.example", risk: { score: 10, label: risk },
    impersonation: { level }, payment: payment ? { level: payment } : null,
  }) as unknown as Report;

  it("goes by signs of a fake site, not setup grades", () => {
    expect(linkLevel(report("clear", "Medium"))).toBe("clear");   // ordinary sites often score Medium on headers
    expect(linkLevel(report("clear", "High"))).toBe("caution");
    expect(linkLevel(report("suspicious"))).toBe("caution");
    expect(linkLevel(report("likely"))).toBe("danger");
    expect(linkLevel(report("reported"))).toBe("danger");
    expect(linkLevel(report("clear", "Low", "danger"))).toBe("danger");
  });

  it("the overall level is the worst of all", () => {
    expect(overallLevel("clear", ["clear", "caution"])).toBe("caution");
    expect(overallLevel("danger", ["clear"])).toBe("danger");
    expect(overallLevel("clear", [])).toBe("clear");
  });
});
