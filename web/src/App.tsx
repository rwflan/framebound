import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
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
import "./controls.css";
import "./film-stock.css";
import { useAutomaticUpdates } from "./useAutomaticUpdates";

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
  const [view, setView] = useState(parseHash);
  const [data, setData] = useState<DeskData | null>(null),
    [error, setError] = useState<unknown>(null),
    [version, setVersion] = useState(0),
    [activeNavigation, setActiveNavigation] = useState<"inbox" | "activity">(
      "inbox",
    );
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
    setError(null);
    loadDesk()
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e);
      });

    return () => {
      live = false;
    };
  }, [version]);
  const refresh = useCallback(() => setVersion((n) => n + 1), []);
  useAutomaticUpdates(refresh);
  const scoped = data?.bundles || [];
  useEffect(() => {
    if (view.name === "inbox" || view.name === "activity")
      setActiveNavigation(view.name);
  }, [view.name]);
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
  const [source, setSource] = useState("all"),
    [order, setOrder] = useState("oldest");
  const timeline = useMemo(
    () =>
      chronology(data?.bundles || [], data?.events || [])
        .filter((e) => source === "all" || e.source === source)
        .sort(
          (a, b) =>
            (order === "oldest" ? 1 : -1) *
            (a.at.localeCompare(b.at) || a.id.localeCompare(b.id)),
        ),
    [data, source, order],
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
      <header className="app-header streamlined-header">
        <button
          className="brand"
          onClick={() => nav({ name: "inbox" })}
          aria-label="Framebound"
        >
          <Icon name="frame" />
          Framebound
        </button>
        <nav className="review-navigation" aria-label="Review views">
          <button
            aria-current={
              activeNavigation === "inbox" && inFilm ? "page" : undefined
            }
            onClick={() => {
              nav({ name: "inbox" });
            }}
          >
            Interventions<span>{interventions.length}</span>
          </button>
          <button
            aria-current={
              activeNavigation === "activity" && inFilm ? "page" : undefined
            }
            onClick={() => nav({ name: "activity" })}
          >
            Timeline
          </button>
        </nav>
        <details className="workspace-switcher">
          <summary aria-label="More workspaces">•••</summary>
          <nav aria-label="Workspaces">
            {[
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
      </header>
      <main
        className={inFilm ? "film-desk" : "operations-desk"}
        data-film-view={
          view.name === "packet"
            ? "sequence"
            : view.name === "activity"
              ? "timeline"
              : "interventions"
        }
      >
        {view.name === "activity" && (
          <div className="timeline-tools">
            <span>History</span>
            <div>
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
            </div>
          </div>
        )}
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
                key="interventions"
                bundles={interventions}
                issues={data.issues}
                events={null}
                projectLabel={(id) =>
                  projects.find((p) => p.id === id)?.name || id
                }
                refs={data.refs}
                filmKey="interventions"
              />
            )}
            {view.name === "activity" && (
              <Collection
                key={"timeline" + source + order}
                bundles={[]}
                issues={data.issues}
                events={timeline}
                projectLabel={(id) =>
                  projects.find((p) => p.id === id)?.name || id
                }
                refs={data.refs}
                filmKey={"timeline" + source + order}
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
                  choices={scoped}
                  onRefresh={refresh}
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
              <div className="operations-content" key={view.name}>
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
    </div>
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
  const focusedId = useRef<string | null>(null);
  const items = events
    ? events.map((e) => ({ id: e.id, bundle: e.bundle, event: e }))
    : bundles.map((b) => ({ id: packetId(b), bundle: b, event: undefined }));
  const retained = items.findIndex((item) => item.id === focusedId.current);
  const selected =
      retained >= 0 ? retained : Math.min(index, Math.max(0, items.length - 1)),
    item = items[selected];
  useEffect(() => {
    if (!focusedId.current && item) focusedId.current = item.id;
  }, [item]);
  const select = (i: number) => {
    focusedId.current = items[i]?.id || null;
    setIndex(i);
    controls.film.current?.reveal(i);
  };
  const open = (i: number) => {
    const entry = items[i];
    if (entry?.bundle) nav({ name: "packet", id: packetId(entry.bundle) });
    else if (entry?.event) setDetail(entry.event);
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
                    onClick={() => {
                      select(i);
                      if (events) open(i);
                    }}
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
        itemName={events ? "event" : "sequence"}
        caption={
          <>
            <strong>{item?.bundle ? actionName(item.bundle) : "Review"}</strong>
            <span>
              {items.length} {events ? "events" : "sequences"}
            </span>
          </>
        }
      >
        {item?.event && item.bundle && (
          <button
            className="reel-secondary"
            onClick={() => setDetail(item.event!)}
          >
            Event details
          </button>
        )}
        <button
          className="reel-primary"
          disabled={!item}
          onClick={() => open(selected)}
        >
          {events && item?.bundle
            ? "Open sequence"
            : events
              ? "Details"
              : "Review"}
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
