import { useCallback, useEffect, useMemo, useState } from "react";
import { api, clearSession, getReviewer, setSession } from "./api";
import type {
  ActivityEventDto,
  IssueDetailDto,
  ReferencesDto,
} from "./api-types";
import { Film, FilmDock, useFilm } from "./Film";
import { PacketWorkspace } from "./PacketWorkspace";
import {
  CompareView,
  CorrectionsView,
  ExportView,
  IssuesView,
  ReferencesView,
  StatusView,
} from "./Operations";
import {
  actionName,
  boundLabel,
  chronology,
  needsReview,
  packetId,
  priority,
  projectId,
  revisionId,
  valueLabel,
} from "./review-model";
import type { Bundle, DeskEvent } from "./review-model";
import { Err, Icon, nav, parseHash, stamp, words } from "./shared";
import { Modal } from "./Modal";
import "./desk.css";

type DeskData = {
  bundles: Bundle[];
  issues: IssueDetailDto[];
  refs: ReferencesDto;
  projects: { id: string; name: string }[];
  events: ActivityEventDto[];
  cursor: string | null;
  more: boolean;
};
async function loadDesk(): Promise<DeskData> {
  const [packets, issues, refs, projects, activity] = await Promise.all([
    api.packets(),
    api.issues(),
    api.references(),
    api.project(),
    api.activity(undefined, 500),
  ]);
  // Bound concurrent media-bundle requests for projects with a large history.
  const bundles: Bundle[] = [];
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(6, packets.packets.length) }, async () => {
      while (next < packets.packets.length) {
        const p = packets.packets[next++];
        bundles.push(await api.packet(String(p.id)));
      }
    }),
  );
  bundles.sort(
    (a, b) =>
      String(a.packet.created_at).localeCompare(String(b.packet.created_at)) ||
      packetId(a).localeCompare(packetId(b)),
  );
  return {
    bundles,
    issues,
    refs,
    projects: projects.projects,
    events: activity.events,
    cursor: activity.cursor || null,
    more: activity.events.length === 500,
  };
}

export default function App() {
  const [view, setView] = useState(parseHash),
    [reviewer, setReviewer] = useState(getReviewer),
    [pairing, setPairing] = useState(false);
  const [data, setData] = useState<DeskData | null>(null),
    [error, setError] = useState<unknown>(null),
    [loading, setLoading] = useState(false),
    [version, setVersion] = useState(0),
    [project, setProject] = useState("all");
  useEffect(() => {
    const update = () => {
      setView(parseHash());
      setVersion((n) => n + 1);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    loadDesk()
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [version]);
  const refresh = useCallback(() => setVersion((n) => n + 1), []);
  const scoped = useMemo(
    () =>
      data?.bundles.filter(
        (b) => project === "all" || projectId(b, data.refs) === project,
      ) || [],
    [data, project],
  );
  const inFilm = ["inbox", "packet", "activity"].includes(view.name);
  const current =
    view.name === "packet" && data
      ? data.bundles.find((b) => packetId(b) === view.id)
      : null;
  const projects = data?.projects || [];
  const interventions = useMemo(() => {
    const latest = new Map<string, Bundle>();
    scoped.forEach((b) => latest.set(String(b.contract.id), b));
    return scoped
      .filter(
        (b) =>
          (latest.get(String(b.contract.id)) === b ||
            data?.issues.some(
              (i) =>
                i.clip_revision_id === revisionId(b) &&
                !["resolved", "cancelled"].includes(i.task_status || "open"),
            )) &&
          needsReview(b, data?.issues || []),
      )
      .sort(
        (a, b) =>
          priority(a, data?.issues || []) - priority(b, data?.issues || []),
      );
  }, [scoped, data]);
  const [collection, setCollection] = useState<"interventions" | "sequences">(
    "interventions",
  );
  const [source, setSource] = useState("all"),
    [order, setOrder] = useState("oldest");
  const timeline = useMemo(
    () =>
      chronology(data?.bundles || [], data?.events || [])
        .filter(
          (e) =>
            (project === "all" ||
              (e.bundle
                ? projectId(e.bundle, data?.refs || null)
                : data?.refs.character_revisions.find(
                    (c) => c.id === e.review?.clip_revision_id,
                  )?.project_id) === project) &&
            (source === "all" || e.source === source),
        )
        .sort(
          (a, b) =>
            (order === "oldest" ? 1 : -1) *
            (a.at.localeCompare(b.at) || a.id.localeCompare(b.id)),
        ),
    [data, project, source, order],
  );
  const loadMore = async () => {
    if (!data?.more) return;
    try {
      const p = await api.activity(data.cursor || undefined, 500);
      setData((d) =>
        d
          ? {
              ...d,
              events: [
                ...d.events,
                ...p.events.filter(
                  (e) => !d.events.some((old) => old.id === e.id),
                ),
              ],
              cursor: p.cursor || d.cursor,
              more: p.events.length === 500,
            }
          : d,
      );
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div className="desk-shell">
      <header className="app-header">
        <button
          className="brand"
          onClick={() => nav({ name: "inbox" })}
          aria-label="Framebound review desk"
        >
          <Icon name="frame" />
          Framebound
        </button>
        <span className="desk-label">Review desk</span>
        <div className="header-end">
          <details className="workspace-switcher">
            <summary>
              Workspace <span>⌄</span>
            </summary>
            <nav aria-label="Workspaces">
              {[
                ["inbox", "Review"],
                ["corrections", "Corrections"],
                ["issues", "Issues"],
                ["references", "References"],
                ["export", "Export"],
                ["status", "Status"],
              ].map(([name, label]) => (
                <button
                  key={name}
                  onClick={(e) => {
                    e.currentTarget.closest("details")?.removeAttribute("open");
                    nav({ name: name as "export" });
                  }}
                >
                  {label}
                </button>
              ))}
            </nav>
          </details>
          <button
            className="reel-icon refresh-button"
            aria-label="Refresh review desk"
            disabled={loading}
            onClick={refresh}
          >
            <Icon name="refresh" />
          </button>
          <button
            className={"reviewer-button " + (reviewer ? "paired" : "")}
            onClick={() => setPairing(true)}
          >
            {reviewer || "Pair reviewer"}
          </button>
        </div>
      </header>
      <main
        className={inFilm ? "film-desk" : "operations-desk"}
        data-film-view={
          view.name === "packet"
            ? "sequence"
            : view.name === "activity"
              ? "timeline"
              : collection
        }
      >
        <div className="reel-menus">
          <label className="reel-project">
            <Icon name="folder" />
            <select
              aria-label="Project"
              value={project}
              onChange={(e) => {
                setProject(e.target.value);
                if (view.name === "packet") nav({ name: "inbox" });
              }}
            >
              <option value="all">All projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
              {data?.bundles.some(
                (b) => projectId(b, data.refs) === "unassigned",
              ) && <option value="unassigned">Unassigned project</option>}
            </select>
          </label>
          <nav className="reel-views" aria-label="Review views">
            <button
              aria-current={
                view.name !== "activity" &&
                collection === "interventions" &&
                inFilm
                  ? "page"
                  : undefined
              }
              onClick={() => {
                setCollection("interventions");
                nav({ name: "inbox" });
              }}
            >
              Interventions <span>{interventions.length}</span>
            </button>
            <button
              aria-current={view.name === "activity" ? "page" : undefined}
              onClick={() => nav({ name: "activity" })}
            >
              Timeline
            </button>
            <button
              aria-current={
                collection === "sequences" && view.name !== "activity" && inFilm
                  ? "page"
                  : undefined
              }
              onClick={() => {
                setCollection("sequences");
                nav({ name: "inbox" });
              }}
            >
              Sequences
            </button>
          </nav>
          <div className="reel-menu-tools">
            {current && (
              <select
                aria-label="Clip revision"
                value={packetId(current)}
                onChange={(e) => nav({ name: "packet", id: e.target.value })}
              >
                {scoped.map((b) => (
                  <option key={packetId(b)} value={packetId(b)}>
                    {actionName(b)} · {revisionId(b)}
                  </option>
                ))}
              </select>
            )}
            {view.name === "activity" && (
              <>
                <select
                  aria-label="Activity source"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                >
                  <option value="all">All activity</option>
                  <option value="framework">Framework</option>
                  <option value="human">Human review</option>
                </select>
                <select
                  aria-label="Chronological order"
                  value={order}
                  onChange={(e) => setOrder(e.target.value)}
                >
                  <option value="oldest">Oldest first</option>
                  <option value="newest">Newest first</option>
                </select>
                {data?.more && (
                  <button onClick={loadMore}>Load more history</button>
                )}
              </>
            )}
          </div>
        </div>
        {Boolean(error) && (
          <div className="desk-error">
            <Err e={error} />
            <button onClick={refresh}>Retry</button>
          </div>
        )}
        {!data && !error && (
          <div className="reel-empty" role="status">
            Loading review desk…
          </div>
        )}
        {data && (
          <>
            {view.name === "inbox" && (
              <Collection
                key={collection + project}
                bundles={
                  collection === "interventions" ? interventions : scoped
                }
                issues={data.issues}
                events={null}
                projectLabel={(id) =>
                  projects.find((p) => p.id === id)?.name || id
                }
                refs={data.refs}
                filmKey={collection + project}
              />
            )}
            {view.name === "activity" && (
              <Collection
                key={"timeline" + project + source + order}
                bundles={[]}
                issues={data.issues}
                events={timeline}
                projectLabel={(id) =>
                  projects.find((p) => p.id === id)?.name || id
                }
                refs={data.refs}
                filmKey={"timeline" + project + source + order}
              />
            )}
            {view.name === "packet" &&
              (current ? (
                <PacketWorkspace
                  key={view.id}
                  bundle={current}
                  refs={data.refs}
                  issues={data.issues}
                  bundles={data.bundles}
                  reviewer={reviewer}
                  onRefresh={refresh}
                  onPair={() => setPairing(true)}
                />
              ) : (
                <div className="reel-empty">
                  Review packet unavailable.{" "}
                  <button onClick={() => nav({ name: "inbox" })}>
                    Back to review
                  </button>
                </div>
              ))}
            {!inFilm && (
              <div className="operations-content" key={view.name + reviewer}>
                {view.name === "compare" && (
                  <CompareView base={view.base} other={view.other} />
                )}
                {view.name === "issues" && (
                  <IssuesView revision={view.revision} />
                )}
                {view.name === "corrections" && <CorrectionsView />}
                {view.name === "export" && <ExportView />}
                {view.name === "references" && <ReferencesView />}
                {view.name === "status" && <StatusView />}
              </div>
            )}
          </>
        )}
      </main>
      {pairing && (
        <Modal
          title={reviewer ? "Reviewer session" : "Pair reviewer"}
          onClose={() => setPairing(false)}
        >
          {reviewer ? (
            <>
              <p>Signed in as {reviewer}</p>
              <button
                onClick={() => {
                  clearSession();
                  setReviewer(null);
                  setPairing(false);
                  refresh();
                }}
              >
                End session
              </button>
            </>
          ) : (
            <Pairing
              onPaired={(r) => {
                setReviewer(r);
                setPairing(false);
                refresh();
              }}
            />
          )}
        </Modal>
      )}
    </div>
  );
}

function Pairing({ onPaired }: { onPaired: (id: string) => void }) {
  const [code, setCode] = useState(""),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  return (
    <form
      className="form-stack"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          const s = await api.reviewerOpen(code.trim());
          setSession(s.session_token, s.reviewer_id);
          onPaired(s.reviewer_id);
        } catch (e) {
          setError(e);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Pairing code
        <input
          autoComplete="off"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          autoFocus
        />
      </label>
      <p className="muted">
        Use the single-use code issued by your project operator.
      </p>
      <Err e={error} />
      <button className="primary" disabled={!code.trim() || busy}>
        {busy ? "Opening…" : "Open session"}
      </button>
    </form>
  );
}

function Collection({
  bundles,
  issues,
  events,
  refs,
  projectLabel,
  filmKey,
}: {
  bundles: Bundle[];
  issues: IssueDetailDto[];
  events: DeskEvent[] | null;
  refs: ReferencesDto;
  projectLabel: (id: string) => string;
  filmKey: string;
}) {
  const controls = useFilm(),
    [index, setIndex] = useState(0),
    [detail, setDetail] = useState<DeskEvent | null>(null);
  const items = events
    ? events.map((e) => ({ id: e.id, bundle: e.bundle, event: e }))
    : bundles.map((b) => ({ id: packetId(b), bundle: b, event: undefined }));
  const selected = Math.min(index, Math.max(0, items.length - 1)),
    item = items[selected];
  const select = (i: number) => {
    setIndex(i);
    controls.film.current?.reveal(i);
  };
  const open = (i: number) => {
    const entry = items[i];
    if (entry?.event) setDetail(entry.event);
    else if (entry?.bundle) nav({ name: "packet", id: packetId(entry.bundle) });
  };
  return (
    <>
      {items.length ? (
        <Film
          ref={controls.film}
          count={items.length}
          filmKey={filmKey}
          selected={selected}
          onStep={select}
          onZoom={controls.setZoom}
          onPosition={controls.setPosition}
        >
          <div className="reel-stock">
            <div className="reel-shot-row">
              {items.map(({ id, bundle: b, event }, i) => {
                const character = refs.character_revisions.find(
                  (c) => c.id === event?.review?.clip_revision_id,
                );
                const frame =
                    b?.frames[Math.min(3, b.frames.length - 1)] ||
                    (character?.identity_asset_ids[0]
                      ? {
                          asset_url: api.assetUrl(
                            character.identity_asset_ids[0],
                          ),
                        }
                      : undefined),
                  openIssues = b
                    ? issues.filter(
                        (iss) =>
                          iss.clip_revision_id === revisionId(b) &&
                          !["resolved", "cancelled"].includes(
                            iss.task_status || "open",
                          ),
                      )
                    : [];
                const title =
                  event?.title ||
                  (openIssues.length
                    ? `${openIssues.length} correction${openIssues.length > 1 ? "s" : ""}`
                    : b?.evaluation.technical_status !== "pass"
                      ? "Check evidence"
                      : "Visual review");
                return (
                  <button
                    key={id}
                    className="reel-shot"
                    aria-pressed={i === selected}
                    aria-label={`${event?.title || actionName(b!)} ${b ? revisionId(b) : event?.actor}`}
                    onClick={() => select(i)}
                    onDoubleClick={() => open(i)}
                  >
                    <span className="shot-aperture">
                      {frame ? (
                        <img
                          draggable={false}
                          loading="lazy"
                          src={frame.asset_url}
                          alt={b ? actionName(b) : ""}
                        />
                      ) : (
                        <span className="event-glyph">
                          <Icon name="check" />
                        </span>
                      )}
                      <span
                        className={
                          "shot-outcome " +
                          (b?.evaluation.technical_status || "")
                        }
                      >
                        {event
                          ? stamp(event.at)
                          : words(b?.evaluation.technical_status)}
                      </span>
                      <span className="shot-caption">
                        <span className="shot-project">
                          {b
                            ? projectLabel(projectId(b, refs))
                            : character?.project_id
                              ? projectLabel(character.project_id)
                              : event?.actor}
                        </span>
                        <strong>{event ? words(title) : actionName(b!)}</strong>
                        <span>
                          {b ? revisionId(b) : event?.review?.clip_revision_id}
                        </span>
                        <span>
                          {event
                            ? event.actor
                            : `${title} · ${words(b?.evaluation.coverage_status)} coverage`}
                        </span>
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </Film>
      ) : (
        <div className="reel-empty">
          {events
            ? "No recorded activity."
            : "No review items in this project."}
        </div>
      )}
      <FilmDock
        controls={controls}
        index={selected}
        count={items.length}
        onSelect={select}
        caption={
          <>
            <strong>{item?.bundle ? actionName(item.bundle) : "Review"}</strong>
            <span>
              {items.length} {events ? "events" : "sequences"}
            </span>
          </>
        }
      >
        <button
          className="reel-primary"
          disabled={!item}
          onClick={() => open(selected)}
        >
          {events ? "Details" : "Review"}
          <Icon name="right" />
        </button>
      </FilmDock>
      {detail && (
        <Modal title={words(detail.title)} onClose={() => setDetail(null)}>
          <div className="event-traversal">
            <button
              aria-label="Previous event"
              disabled={items.findIndex((e) => e.id === detail.id) <= 0}
              onClick={() => {
                const i = items.findIndex((e) => e.id === detail.id) - 1;
                select(i);
                setDetail(items[i].event!);
              }}
            >
              <Icon name="left" />
            </button>
            <span>
              {items.findIndex((e) => e.id === detail.id) + 1} / {items.length}
            </span>
            <button
              aria-label="Next event"
              disabled={
                items.findIndex((e) => e.id === detail.id) >= items.length - 1
              }
              onClick={() => {
                const i = items.findIndex((e) => e.id === detail.id) + 1;
                select(i);
                setDetail(items[i].event!);
              }}
            >
              <Icon name="right" />
            </button>
          </div>
          <div className="event-meta">
            <time dateTime={detail.at} title={detail.at}>
              {stamp(detail.at)}
            </time>
            <span>{detail.actor}</span>
          </div>
          <p>{detail.review?.note}</p>
          <dl className="facts">
            <dt>Revision</dt>
            <dd>
              {detail.bundle
                ? revisionId(detail.bundle)
                : detail.review?.clip_revision_id || "—"}
            </dd>
            <dt>Source</dt>
            <dd>{detail.source}</dd>
            <dt>Event</dt>
            <dd>{detail.id}</dd>
          </dl>
          {detail.checks?.map((c, i) => (
            <div className={"check-row " + c.outcome} key={i}>
              <strong>{words(c.constraint_id)}</strong>
              <span>
                {c.scope} · {words(c.outcome)}
              </span>
              <p>
                {valueLabel(c)} · {boundLabel(c)} · {c.reason}
              </p>
            </div>
          ))}
          {detail.bundle && (
            <button
              className="primary"
              onClick={() => {
                setDetail(null);
                nav({ name: "packet", id: packetId(detail.bundle!) });
              }}
            >
              Open sequence <Icon name="right" />
            </button>
          )}
        </Modal>
      )}
    </>
  );
}
