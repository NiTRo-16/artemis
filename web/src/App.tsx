import { useEffect } from "react";
import { Route, Routes, useLocation, useNavigate } from "react-router";
import { useAccount } from "./account";
import { AuthDialog } from "./components/AuthDialog";
import { Frame } from "./components/Frame";
import { SettingsDialog } from "./components/SettingsDialog";
import { ComingSoonPage } from "./pages/ComingSoonPage";
import { HistoryPage } from "./pages/HistoryPage";
import { MessagePage } from "./pages/MessagePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { QrPage } from "./pages/QrPage";
import { ResultPage, SharedPage } from "./pages/ResultPage";
import { ScanPage } from "./pages/ScanPage";

/** Links from account emails: /verify#<token> and /reset#<token>. The token sits after "#" so it never
 *  reaches the server's logs; take it, then clean the address bar so it isn't left in history. */
function EmailLink({ mode }: { mode: "verify" | "reset" }) {
  const { openAuth } = useAccount();
  const navigate = useNavigate();
  useEffect(() => {
    const token = location.hash.slice(1);
    navigate("/", { replace: true });
    if (/^[A-Za-z0-9_-]{20,200}$/.test(token)) openAuth(mode, token);
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function App() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return (
    <Frame>
      <Routes>
        <Route path="/" element={<ScanPage />} />
        <Route path="/scan/:id" element={<ResultPage />} />
        <Route path="/r/:id" element={<SharedPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/messages" element={<MessagePage />} />
        <Route path="/qr" element={<QrPage />} />
        <Route path="/watch" element={<ComingSoonPage tool="watch" />} />
        <Route path="/developers" element={<ComingSoonPage tool="developers" />} />
        <Route path="/verify" element={<EmailLink mode="verify" />} />
        <Route path="/reset" element={<EmailLink mode="reset" />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <AuthDialog />
      <SettingsDialog />
    </Frame>
  );
}
