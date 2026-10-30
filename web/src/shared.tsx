import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export type View =
  | {
      name:
        | "inbox"
        | "corrections"
        | "export"
        | "activity"
        | "status"
        | "references";
    }
  | { name: "packet"; id: string }
  | { name: "compare"; base: string; other: string }
  | { name: "issues"; revision?: string };
export function parseHash(): View {
  const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
  const q = new URLSearchParams(query),
    parts = path.split("/");
  if (parts[0] === "packet" && parts[1])
    return { name: "packet", id: decodeURIComponent(parts[1]) };
  if (path === "compare" && q.get("base") && q.get("other"))
    return { name: "compare", base: q.get("base")!, other: q.get("other")! };
  if (path === "issues")
    return { name: "issues", revision: q.get("revision") || undefined };
  if (
    ["corrections", "export", "activity", "status", "references"].includes(path)
  )
    return { name: path as "export" };
  return { name: "inbox" };
}
export function nav(v: View) {
  location.hash =
    v.name === "inbox"
      ? "/"
      : v.name === "packet"
        ? `/packet/${encodeURIComponent(v.id)}`
        : v.name === "compare"
          ? `/compare?base=${encodeURIComponent(v.base)}&other=${encodeURIComponent(v.other)}`
          : v.name === "issues"
            ? `/issues${v.revision ? "?revision=" + encodeURIComponent(v.revision) : ""}`
            : "/" + v.name;
}
export function Err({ e }: { e: unknown }) {
  return e ? (
    <p className="error" role="alert">
      {e instanceof ApiError
        ? e.message
        : e instanceof Error
          ? e.message
          : String(e)}
    </p>
  ) : null;
}
export function useLoad<T>(key: string, fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null),
    [err, setErr] = useState<unknown>(null),
    [n, setN] = useState(0);
  const previousKey = useRef(key);
  useEffect(() => {
    let live = true;
    if (previousKey.current !== key) setData(null);
    previousKey.current = key;
    setErr(null);
    fn()
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setErr(e);
      });
    return () => {
      live = false;
    };
  }, [key, n]);
  useEffect(() => {
    const changed = () => setN((x) => x + 1);
    window.addEventListener("framebound:changed", changed);
    return () => window.removeEventListener("framebound:changed", changed);
  }, []);
  return { data, err, reload: () => setN((x) => x + 1) };
}
export function usePreload(urls: string[]) {
  const [imgs, setImgs] = useState<Map<string, HTMLImageElement>>(new Map()),
    [errors, setErrors] = useState<Map<string, string>>(new Map());
  const key = [...new Set(urls)].sort().join("|");
  useEffect(() => {
    let live = true;
    const next = new Map<string, HTMLImageElement>(),
      errs = new Map<string, string>();
    const list = [...new Set(urls)];
    let done = 0;
    if (!list.length) {
      setImgs(next);
      setErrors(errs);
      return;
    }
    const finish = () => {
      if (++done === list.length && live) {
        setImgs(new Map(next));
        setErrors(new Map(errs));
      }
    };
    list.forEach((u) => {
      const img = new Image();
      img.onload = () => {
        next.set(u, img);
        finish();
      };
      img.onerror = () => {
        errs.set(u, "Failed to load frame");
        finish();
      };
      img.src = u;
    });
    return () => {
      live = false;
    };
  }, [key]);
  return { imgs, errors };
}
export const words = (s: unknown) =>
  String(s ?? "Unavailable").replace(/[_-]/g, " ");
export const stamp = (s: string) =>
  new Date(s).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
export function Icon({
  name,
}: {
  name:
    | "left"
    | "right"
    | "play"
    | "pause"
    | "plus"
    | "close"
    | "check"
    | "folder"
    | "refresh"
    | "frame"
    | "inbox"
    | "history"
    | "search"
    | "expand"
    | "film";
}) {
  const paths = {
    left: "m14 6-6 6 6 6",
    right: "m10 6 6 6-6 6",
    play: "m8 5 11 7-11 7Z",
    pause: "M9 5v14M15 5v14",
    plus: "M12 5v14M5 12h14",
    close: "m6 6 12 12M18 6 6 18",
    check: "m5 12 4 4L19 6",
    folder: "M3 7V5h6l2 2h10v13H3Z",
    refresh: "M20 8a8 8 0 1 0 0 8M20 3v5h-5",
    frame: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5",
    inbox: "M4 4h16v16H4ZM4 14h5l1 3h4l1-3h5",
    search: "m16 16 5 5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    film: "M3 3h18v18H3ZM7 3v18M17 3v18M3 8h4m-4 8h4M17 8h4m-4 8h4",
    expand: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5",
    history: "M4 8a9 9 0 1 1-1 7M4 3v5h5M12 7v5l3 2",
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
