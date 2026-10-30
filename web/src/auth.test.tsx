// The sign-in dialog: Google only when the server offers it, the password rule, and the strength meter.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountProvider, useAccount } from "./account";
import { AuthDialog, passwordStrength } from "./components/AuthDialog";

HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.open = true; };
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.open = false; };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function mockMe(google: boolean) {
  const calls: string[] = [];
  globalThis.fetch = (async (url: RequestInfo | URL) => {
    calls.push(String(url));
    return new Response(JSON.stringify(String(url) === "/api/me" ? { account: null, google_signin: google } : {}));
  }) as typeof fetch;
  return calls;
}

function Opened({ mode }: { mode: "signup" | "login" }) {
  const { openAuth } = useAccount();
  useEffect(() => { openAuth(mode); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  return <AuthDialog />;
}

function show(mode: "signup" | "login") {
  return render(<MemoryRouter><AccountProvider><Opened mode={mode} /></AccountProvider></MemoryRouter>);
}

describe("password strength", () => {
  it("rates by length first", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("short1")).toBe(1);
    expect(passwordStrength("tenletters")).toBe(2);
    expect(passwordStrength("sunrise-kite-42")).toBe(4);
  });
});

describe("sign-in dialog", () => {
  it("offers Google only when the server has it set up", async () => {
    mockMe(true);
    show("signup");
    expect(await screen.findByRole("link", { name: "Continue with Google" })).toHaveProperty("href", expect.stringContaining("/api/auth/google"));
    cleanup();
    mockMe(false);
    show("signup");
    await screen.findByRole("heading", { name: "Create your account" });
    expect(screen.queryByRole("link", { name: "Continue with Google" })).toBeNull();
  });

  it("asks for a name before sending anything", async () => {
    const calls = mockMe(false);
    show("signup");
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "asha@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough password" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Enter your name.");
    expect(calls.filter((c) => c === "/api/signup")).toHaveLength(0);
  });

  it("refuses a short password before sending anything", async () => {
    const calls = mockMe(false);
    show("signup");
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Asha" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "asha@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Use a password of at least 10 characters.");
    expect(calls.filter((c) => c === "/api/signup")).toHaveLength(0);
  });

  it("shows the password on request and offers a reset when logging in", async () => {
    mockMe(false);
    show("login");
    const pw = await screen.findByLabelText("Password");
    expect(pw.getAttribute("type")).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(pw.getAttribute("type")).toBe("text");
    expect(screen.getByRole("button", { name: "Forgot password?" })).toBeTruthy();
  });
});
