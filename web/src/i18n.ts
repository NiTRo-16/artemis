// The site's languages. English text is the key, so anything missing from hi.json shows in English.
// Scan reasons built on the server aren't translated yet; they pass through t() and stay in English.
import { createContext, useCallback, useContext, type ReactNode } from "react";
import hi from "./hi.json";

export type Lang = "en" | "hi";
export type Translate = (text: string, vars?: Record<string, string | number>) => string;

const HI: Record<string, string> = hi;
const PREVIEW_KEY = "artemis.hindi";
// Off until a fluent Hindi speaker has read it. /?hindi=1 shows the option in that browser for review.
const HINDI_PUBLIC = false;
let current: Lang = "en";

// Server messages that contain a value.
const PATTERNS: [RegExp, string][] = [
  [/^Confirm your email first\. We've sent a new link to (.+)\.$/, "पहले अपना ईमेल पक्का करें। हमने $1 पर नया लिंक भेजा है।"],
  [/^(.+) points to a private or reserved address, so it can't be scanned\.$/, "$1 एक निजी या आरक्षित पते पर जाता है, इसलिए इसे स्कैन नहीं किया जा सकता।"],
  [/^Impersonation check: (.+)$/, "नकल की जांच: $1"],
  [/^Payment check: (.+)$/, "पेमेंट जांच: $1"],
  [/^Link leads to a different site \((.+)\) that wasn't checked$/, "लिंक दूसरी साइट ($1) पर ले जाता है, जिसकी जांच नहीं हुई"],
];

/** Marks text that's translated later, where it's used, so the tests can still find it. */
export const tk = (text: string) => text;

export function setCurrentLanguage(lang: Lang) {
  current = lang;
  document.documentElement.lang = lang;
}

function inHindi(text: string): string {
  if (HI[text]) return HI[text];
  const official = /^Official (.+) domain$/.exec(text);
  if (official) return HI["Official {brand} domain"].replace("{brand}", official[1]);
  for (const [pattern, hindi] of PATTERNS) {
    if (pattern.test(text)) {
      const value = pattern.exec(text)![1];
      return hindi.replace("$1", /^(Impersonation|Payment) check/.test(text) ? HI[value] ?? value : value);
    }
  }
  return text;
}

export function translate(text: string, lang: Lang = current, vars?: Record<string, string | number>): string {
  let out = lang === "hi" ? inHindi(text) : text;
  for (const [key, value] of Object.entries(vars ?? {})) out = out.replaceAll(`{${key}}`, String(value));
  return out;
}

export const LanguageContext = createContext<Lang>("en");

export function useT(): Translate {
  const lang = useContext(LanguageContext);
  return useCallback((text, vars) => translate(text, lang, vars), [lang]);
}

export function useLang(): Lang {
  return useContext(LanguageContext);
}

/** Dates in the page's language. */
export const dateLocale = (lang: Lang) => (lang === "hi" ? "hi-IN" : undefined);

/** Text with {slots} filled by links or other elements. */
export function withSlots(text: string, slots: Record<string, ReactNode>): ReactNode[] {
  return text.split(/(\{\w+\})/).map((part) => {
    const slot = /^\{(\w+)\}$/.exec(part);
    return slot ? slots[slot[1]] : part;
  });
}

export function languageOptionShown(): boolean {
  if (HINDI_PUBLIC) return true;
  try {
    if (new URLSearchParams(location.search).get("hindi") === "1") localStorage.setItem(PREVIEW_KEY, "1");
    return localStorage.getItem(PREVIEW_KEY) === "1";
  } catch {
    return false;
  }
}
