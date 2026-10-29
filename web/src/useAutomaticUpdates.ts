import { useEffect } from "react";
import { api } from "./api";

/** A lightweight persistent-store marker also sees writes from CLI/worker processes. */
export function useAutomaticUpdates(onChange: () => void) {
  useEffect(() => {
    let stopped = false,
      running = false,
      revision = "",
      failed = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      clearTimeout(timer);
      if (stopped || running || document.visibilityState === "hidden") return;
      running = true;
      try {
        const next = await api.changes();
        if (stopped) return;
        if ((revision && next.revision !== revision) || failed) {
          onChange();
          window.dispatchEvent(new Event("framebound:changed"));
        }
        revision = next.revision;
        failed = false;
      } catch {
        failed = true;
      } finally {
        running = false;
        if (!stopped) timer = setTimeout(check, 1500);
      }
    };
    const visible = () => {
      if (document.visibilityState === "visible") void check();
    };
    void check();
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    return () => {
      stopped = true;
      clearTimeout(timer);
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [onChange]);
}
