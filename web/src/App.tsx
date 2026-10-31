import {UtilitiesMenu,UtilityWindow} from './DeskUtilities';
import {KeyboardGuide} from './KeyboardGuide';
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  ActivityEventDto,
  IssueDetailDto,
  ReferencesDto,
} from "./api-types";
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
  attentionSlot,
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
import { useAutomaticUpdates } from "./useAutomaticUpdates";
import "./desk.css";
import { AgentDesk, useAgentDesk } from "./AgentDesk";
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

const shortRevision = (b: Bundle) =>
  revisionId(b).match(/r\d+$/i)?.[0] || revisionId(b);


export default function App() {
  const {data,error,refresh}=useAgentDesk();
  const [hash,setHash]=useState(location.hash);
  useEffect(()=>{const changed=()=>setHash(location.hash);window.addEventListener('hashchange',changed);return()=>window.removeEventListener('hashchange',changed);},[]);
  if(error)return <Err e={error}/>;
  if(!data)return <p>Loading workspace…</p>;
  const legacy = /^#\/(packet|compare|issues|corrections)/.test(hash);
  if(data.runs.length && !legacy)return <AgentDesk data={data} onChange={refresh}/>;
  return <LegacyApp/>;
}

function LegacyApp() {
  const [view, setView] = useState(parseHash);
  const [data, setData] = useState<DeskData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [version, setVersion] = useState(0);
  const [navigation, setNavigation] = useState<"inbox" | "activity">("inbox");
  const [source, setSource] = useState("all"),
    [order, setOrder] = useState("oldest");
  const [detail, setDetail] = useState<DeskEvent | null>(null);
  const [searching, setSearching] = useState(false),
    [query, setQuery] = useState("");
  const [searchIndex, setSearchIndex] = useState(0);
  const [opened, setOpened] = useState<string[]>([]);
  const retained = useRef<string | null>(
    view.name === "packet" ? view.id : null,
  );
  useEffect(() => {
    const update = () => setView(parseHash());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    if (view.name === "inbox" || view.name === "activity")
      setNavigation(view.name);
    if (view.name === "packet") retained.current = view.id;
  }, [view]);
  useEffect(() => {
    let live = true;
    loadDesk()
      .then((d) => {
        if (live) {
          setData(d);
          setError(null);
        }
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
  const bundles = data?.bundles || [];
  const interventions = useMemo(() => {
    const latest = new Map<string, Bundle>();
    bundles.forEach((b) => latest.set(String(b.contract.id), b));
    return bundles
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
  }, [data]);
  const timeline = useMemo(
    () =>
      chronology(bundles, data?.events || [])
        .filter((e) => source === "all" || e.source === source)
        .sort(
          (a, b) =>
            (order === "oldest" ? 1 : -1) *
            (a.at.localeCompare(b.at) || a.id.localeCompare(b.id)),
        ),
    [data, source, order],
  );
  const inFilm = ["inbox", "packet", "activity"].includes(view.name);
  const current =
    view.name === "packet"
      ? bundles.find((b) => packetId(b) === view.id)
      : bundles.find((b) => packetId(b) === retained.current) ||
        interventions[0] ||
        bundles[bundles.length - 1];
  useEffect(() => {
    if (!current || !inFilm) return;
    const id = packetId(current);
    retained.current = id;
    setOpened((ids) => (ids.includes(id) ? ids : [...ids, id]));
  }, [current?.packet.id, inFilm]);
  const labelProject = (id: string) =>
    data?.projects.find((p) => p.id === id)?.name ||
    (id === "unassigned" ? "Unassigned" : id);
  const eventProject = (event: DeskEvent) =>
    event.bundle
      ? projectId(event.bundle, data?.refs || null)
      : data?.refs.character_revisions.find(
          (c) => c.id === event.review?.clip_revision_id,
        )?.project_id || "unassigned";
  const rows: {
    id: string;
    bundle?: Bundle;
    event?: DeskEvent;
    project: string;
  }[] =
    navigation === "activity"
      ? timeline.map((event) => ({
          id: event.id,
          bundle: event.bundle,
          event,
          project: eventProject(event),
        }))
      : interventions.map((bundle) => ({
          id: packetId(bundle),
          bundle,
          project: projectId(bundle, data?.refs || null),
        }));
  const grouped = new Map<string, typeof rows>();
  rows.forEach((row) =>
    grouped.set(row.project, [...(grouped.get(row.project) || []), row]),
  );
  const matching = bundles.filter((b) =>
    `${actionName(b)} ${revisionId(b)} ${labelProject(projectId(b, data?.refs || null))}`
      .toLowerCase()
      .includes(query.toLowerCase().trim()),
  );
  const nextReview = useCallback(
    (direction = 1) => {
      if (!interventions.length) return;
      const index = interventions.findIndex(
        (b) => packetId(b) === retained.current,
      );
      nav({
        name: "packet",
        id: packetId(
          interventions[
            (index + direction + interventions.length) % interventions.length
          ],
        ),
      });
    },
    [interventions],
  );
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (!document.querySelector("dialog[open]")) {
          setSearching(true);
          setQuery("");
          setSearchIndex(0);
        }
        return;
      }
      if (
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        (e.target as HTMLElement).closest("dialog,input,textarea,select")
      )
        return;
      if (inFilm && ["j", "k"].includes(e.key.toLowerCase())) {
        e.preventDefault();
        nextReview(e.key.toLowerCase() === "j" ? 1 : -1);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [inFilm, nextReview]);
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
      <div className="desk-window">
        <header className="app-header">
          <button
            className="brand"
            onClick={() => nav({ name: "inbox" })}
            aria-label="Framebound"
          >
            <Icon name="frame" />
            <span>Framebound</span>
          </button>
          <button
            className="search-launch"
            aria-label="Find sequence"
            onClick={() => {
              setSearching(true);
              setQuery("");
              setSearchIndex(0);
            }}
          >
            <Icon name="search" />
            <span>Find sequence</span>
            <kbd>⌘ K</kbd>
          </button>
          <UtilitiesMenu active={view.name==='references'?'reviewed-guides':view.name} extras={[{href:'#/corrections',title:'Correction tasks'},{href:'#/issues',title:'Issue records'}]}/>
        </header>
        <div className="desktop-body">
          <aside className="review-sidebar">
            <nav className="review-navigation" aria-label="Review views">
              <button
                aria-current={
                  navigation === "inbox" && inFilm ? "page" : undefined
                }
                onClick={() => nav({ name: "inbox" })}
              >
                <span className="nav-symbol inbox-icon">
                  <Icon name="inbox" />
                </span>
                <span>Interventions</span>
                <span className="nav-count">{interventions.length}</span>
              </button>
              <button
                aria-current={
                  navigation === "activity" && inFilm ? "page" : undefined
                }
                onClick={() => nav({ name: "activity" })}
              >
                <span className="nav-symbol timeline-icon">
                  <Icon name="history" />
                </span>
                <span>Timeline</span>
              </button>
            </nav>
            {navigation === "activity" && (
              <div className="timeline-tools">
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
              </div>
            )}
            <div
              className="review-queue"
              aria-label={
                navigation === "activity"
                  ? "Project timeline"
                  : "Intervention queue"
              }
            >
              {[...grouped].map(([project, entries]) => (
                <section key={project} className="queue-project">
                  <header className="queue-heading">
                    <Icon name="folder" />
                    <span>{labelProject(project)}</span>
                    <small>{entries.length}</small>
                  </header>
                  {entries.map(({ id, bundle: b, event }) => {
                    const frame =
                      b?.frames[attentionSlot(b, data?.issues || [])];
                    const openIssues = b
                      ? data?.issues.filter(
                          (i) =>
                            i.clip_revision_id === revisionId(b) &&
                            !["resolved", "cancelled"].includes(
                              i.task_status || "open",
                            ),
                        ) || []
                      : [];
                    const flagged =
                      b?.evaluation.results.filter((c) =>
                        ["fail", "error", "unmeasured"].includes(c.outcome),
                      ).length || 0;
                    const description = event
                      ? words(event.title)
                      : openIssues.length
                        ? `${openIssues.length} correction${openIssues.length === 1 ? "" : "s"}`
                        : flagged
                          ? `${flagged} flagged check${flagged === 1 ? "" : "s"}`
                          : b?.evaluation.coverage_status !== "complete"
                            ? `${words(b?.evaluation.coverage_status)} coverage`
                            : b?.evaluation.technical_status !== "pass"
                              ? `Technical ${words(b?.evaluation.technical_status)}`
                              : ["rejected", "needs_changes"].includes(
                                    String(b?.current_decision.acceptance),
                                  )
                                ? words(b?.current_decision.acceptance)
                                : b?.packet.comparison_revision_id
                                  ? "Replacement"
                                  : "Visual review";
                    return (
                      <div
                        className={"queue-row" + (event ? " timeline-row" : "")}
                        key={id}
                      >
                        <button
                          className="queue-item"
                          aria-current={
                            b && current && packetId(b) === packetId(current)
                              ? "true"
                              : undefined
                          }
                          aria-label={
                            event
                              ? `${event.title} ${b ? revisionId(b) : event.actor}`
                              : `${b ? actionName(b) : "Review"} ${b ? revisionId(b) : ""}`
                          }
                          onClick={() =>
                            b
                              ? nav({ name: "packet", id: packetId(b) })
                              : event && setDetail(event)
                          }
                        >
                          <span
                            className={
                              "queue-thumb " +
                              (b?.evaluation.technical_status || "")
                            }
                          >
                            {frame ? (
                              <img
                                draggable={false}
                                src={frame.asset_url}
                                alt=""
                                loading="lazy"
                              />
                            ) : (
                              <Icon name="check" />
                            )}
                          </span>
                          <span>
                            <strong>
                              {b ? actionName(b) : words(event?.title)}
                            </strong>
                            <small>{description}</small>
                            {event && (
                              <time dateTime={event.at} title={event.at}>
                                {stamp(event.at)}
                              </time>
                            )}
                          </span>
                          {b && (
                            <span
                              className="queue-revision"
                              title={revisionId(b)}
                            >
                              {shortRevision(b)}
                            </span>
                          )}
                        </button>
                        {event && b && (
                          <button
                            className="event-details-button"
                            aria-label={`Event details: ${event.title} ${revisionId(b)}`}
                            onClick={() => setDetail(event)}
                          >
                            ···
                          </button>
                        )}
                      </div>
                    );
                  })}
                </section>
              ))}
              {data && !rows.length && (
                <p className="queue-empty">
                  {navigation === "activity"
                    ? "No activity"
                    : "No interventions"}
                </p>
              )}
              {navigation === "activity" && data?.more && (
                <button className="load-history" onClick={loadMore}>
                  Load earlier activity
                </button>
              )}
            </div>
            <div className="sidebar-footer">
              <button
                disabled={!interventions.length}
                onClick={() => nextReview()}
              >
                Next intervention <span>↓ J</span>
              </button>
            </div>
          </aside>
          <main
            className={inFilm ? "film-desk" : "operations-desk"}
            data-film-view={
              view.name === "activity"
                ? "timeline"
                : view.name === "packet"
                  ? "sequence"
                  : "interventions"
            }
          >
            {Boolean(error) && (
              <div className="desk-error">
                <Err e={error} />
                <button onClick={refresh}>Retry</button>
              </div>
            )}
            {!data && !error && (
              <div className="reel-empty" role="status">
                Loading…
              </div>
            )}
            {data && inFilm && (
              <>
                {opened.length > 1 && (
                  <nav className="document-tabs" aria-label="Open sequences">
                    {opened
                      .map((id) => bundles.find((b) => packetId(b) === id))
                      .filter((b): b is Bundle => Boolean(b))
                      .map((b) => (
                        <button
                          key={packetId(b)}
                          aria-current={
                            current && packetId(b) === packetId(current)
                              ? "page"
                              : undefined
                          }
                          onClick={() =>
                            nav({ name: "packet", id: packetId(b) })
                          }
                        >
                          {actionName(b)} · {shortRevision(b)}
                        </button>
                      ))}
                  </nav>
                )}
                {current ? (
                  <PacketWorkspace
                    key={packetId(current)}
                    bundle={current}
                    refs={data.refs}
                    issues={data.issues}
                    bundles={bundles}
                    onRefresh={refresh}
                  />
                ) : (
                  <div className="reel-empty">
                    {view.name === "packet"
                      ? "Review packet unavailable"
                      : "No sequences"}
                  </div>
                )}
              </>
            )}
            {data && !inFilm && (
              <div className={view.name==='compare'?'operations-content':'utility-host'} key={view.name}>
                {view.name === "compare" && (
                  <CompareView base={view.base} other={view.other} />
                )}
                {view.name === "issues" && (
                  <UtilityWindow view="issues"><IssuesView revision={view.revision} /></UtilityWindow>
                )}
                {view.name === "corrections" && <UtilityWindow view="corrections"><CorrectionsView /></UtilityWindow>}
                {view.name === "export" && <UtilityWindow view="export"><ExportView /></UtilityWindow>}
                {view.name === "references" && <UtilityWindow view="reviewed-guides"><ReferencesView /></UtilityWindow>}
                {view.name === "status" && <UtilityWindow view="status"><StatusView /></UtilityWindow>}
              </div>
            )}
          </main>
        </div>
        <KeyboardGuide/>
        {searching && (
          <Modal title="Find sequence" onClose={() => setSearching(false)}>
            <div className="command-palette">
              <input
                autoFocus
                aria-label="Search sequences"
                placeholder="Sequence or revision…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSearchIndex(0);
                }}
                onKeyDown={(e) => {
                  if (["ArrowDown", "ArrowUp"].includes(e.key)) {
                    e.preventDefault();
                    setSearchIndex(
                      (i) =>
                        (i +
                          (e.key === "ArrowDown" ? 1 : -1) +
                          matching.length) %
                        Math.max(1, matching.length),
                    );
                  }
                  if (e.key === "Enter" && matching[searchIndex]) {
                    e.preventDefault();
                    setSearching(false);
                    nav({
                      name: "packet",
                      id: packetId(matching[searchIndex]),
                    });
                  }
                }}
              />
              <div className="search-results">
                {matching.map((b, i) => (
                  <button
                    className={i === searchIndex ? "active" : ""}
                    key={packetId(b)}
                    onClick={() => {
                      setSearching(false);
                      nav({ name: "packet", id: packetId(b) });
                    }}
                  >
                    <strong>
                      {actionName(b)} · {shortRevision(b)}
                    </strong>
                    <small>
                      {labelProject(projectId(b, data?.refs || null))} ·{" "}
                      {words(b.evaluation.technical_status)}
                    </small>
                  </button>
                ))}
                {!matching.length && <p>No matches</p>}
              </div>
            </div>
          </Modal>
        )}
        {detail && (
          <Modal title={words(detail.title)} onClose={() => setDetail(null)}>
            <div className="event-detail">
              <time dateTime={detail.at}>{stamp(detail.at)}</time>
              <p>{detail.review?.note}</p>
              <dl className="facts">
                <dt>Revision</dt>
                <dd>
                  {detail.bundle
                    ? revisionId(detail.bundle)
                    : detail.review?.clip_revision_id || "—"}
                </dd>
                <dt>Actor</dt>
                <dd>{detail.actor}</dd>
                <dt>Source</dt>
                <dd>{detail.source}</dd>
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
            </div>
          </Modal>
        )}
      </div>
    </div>
  );
}
