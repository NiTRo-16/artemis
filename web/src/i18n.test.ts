import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import hi from "./hi.json";
import { translate } from "./i18n";

const HI: Record<string, string> = hi;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !name.includes(".test.") ? [path] : [];
  });
}

// Literal text passed to t(), tk() or translate(), including each side of a ?: inside t().
function usedStrings(): Set<string> {
  const found = new Set<string>();
  for (const file of sources(join(__dirname))) {
    const code = readFileSync(file, "utf-8");
    for (const call of code.matchAll(/\b(?:t|tk|translate)\(((?:[^()"]|"(?:[^"\\]|\\.)*"|\([^()]*\))*)\)/g)) {
      for (const literal of call[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)) {
        const text = JSON.parse(`"${literal[1]}"`) as string;
        if (text && /[A-Za-z]/.test(text)) found.add(text);
      }
    }
  }
  return found;
}

describe("Hindi", () => {
  it("has every piece of text the site uses", () => {
    const used = [...usedStrings()];
    expect(used.length).toBeGreaterThan(200);
    const codeWord = /^[a-z]+$/;   // conditions inside t(), like mode === "login"
    expect(used.filter((text) => !HI[text] && !codeWord.test(text))).toEqual([]);
  });

  it("keeps the same placeholders", () => {
    const slots = (text: string) => [...text.matchAll(/\{\w+\}/g)].map((m) => m[0]).sort();
    for (const [english, hindi] of Object.entries(HI)) expect(slots(hindi), english).toEqual(slots(english));
  });

  it("keeps the numbers and names that people act on", () => {
    for (const [english, hindi] of Object.entries(HI)) {
      for (const must of ["1930", "SEBI", "RBI", "OTP", "PIN", "UPI"]) {
        if (english.includes(must)) expect(hindi, english).toContain(must);
      }
    }
  });

  it("has no em dashes", () => {
    expect(Object.values(HI).filter((text) => text.includes("—"))).toEqual([]);
  });

  it("translates, fills in values, and falls back to English", () => {
    expect(translate("Log in", "en")).toBe("Log in");
    expect(translate("Log in", "hi")).toBe("लॉग इन");
    expect(translate("Continue to {site}", "hi", { site: "a.com" })).toBe("a.com पर जाएं");
    expect(translate("Registered only 27 days ago", "hi")).toBe("Registered only 27 days ago");
    expect(translate("Official HDFC Bank domain", "hi")).toBe("HDFC Bank का आधिकारिक डोमेन");
    expect(translate("Impersonation check: Suspicious", "hi")).toBe("नकल की जांच: संदिग्ध");
  });
});
