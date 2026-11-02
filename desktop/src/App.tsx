import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import logo from "./assets/logo.svg";
import { TitleBar } from "./components/TitleBar";
import { APP_VERSION, BUILD_REVISION, formatBuildLabel } from "./appVersion";
import {
  ACCEPTED_TYPES_TEXT,
  chooseFolder,
  chooseImages,
  countSperm,
  homeFolder,
  isDesktopShell,
  imageUrl,
  openDirectory,
  previewImages,
  type CliEvent,
} from "./native";
import {
  baseName,
  batchStats,
  COLOR_KEY,
  compareToMean,
  countTable,
  folderTimestamp,
  formatNumber,
  parentPath,
  type ImageSummary,
} from "./stats";

type View = "count" | "about";
// empty -> loading (previews) -> ready -> counting -> done
type Phase = "empty" | "loading" | "ready" | "counting" | "done";

type Selection = {
  inputs: string[];
  /** Shown above the title, e.g. the folder name. */
  label: string;
  /** Start of the results folder name. */
  base: string;
};

type Item = {
  name: string;
  image: string;
  preview?: string;
  thumb?: string;
  overlay?: string;
  summary?: ImageSummary;
};

function message(reason: unknown): string {
  if (reason instanceof Error) return reason.message;
  return typeof reason === "string" ? reason : "Something went wrong.";
}

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export default function App() {
  const [view, setView] = useState<View>("count");
  const [phase, setPhase] = useState<Phase>("empty");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [current, setCurrent] = useState(0);
  const [showOverlay, setShowOverlay] = useState(true);
  const [resultsParent, setResultsParent] = useState("");
  const [outputRoot, setOutputRoot] = useState("");
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [error, setError] = useState("");
  const thumbRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!isDesktopShell()) return;
    void homeFolder()
      .then((home) => setResultsParent(`${home}/EyeSpySC results`))
      .catch(() => setResultsParent(""));
  }, []);

  const updateItem = (index: number, change: Partial<Item>) => {
    setItems((previous) =>
      previous.map((item, position) => (position === index ? { ...item, ...change } : item)),
    );
  };

  const busy = phase === "loading" || phase === "counting";

  const begin = async (next: Selection) => {
    setSelection(next);
    setItems([]);
    setCurrent(0);
    setShowOverlay(true);
    setOutputRoot("");
    setError("");
    setProgress({ done: 0, total: 0 });
    setPhase("loading");
    let loaded = 0;
    try {
      await previewImages(next.inputs, (event: CliEvent) => {
        if (event.event === "start") setProgress({ done: 0, total: event.total });
        if (event.event !== "image" || !event.preview) return;
        const index = event.index - 1;
        const loadedItem = { name: event.name, image: event.image, preview: event.preview, thumb: event.thumb };
        loaded += 1;
        setItems((previous) => {
          const copy = [...previous];
          copy[index] = loadedItem;
          return copy;
        });
        setProgress({ done: event.index, total: event.total });
      });
      if (loaded === 0) {
        setError("EyeSpySC finished reading the images but received none. Please report this.");
        setSelection(null);
        setPhase("empty");
        return;
      }
      setPhase("ready");
    } catch (reason) {
      setError(message(reason));
      setPhase(loaded > 0 ? "ready" : "empty");
    }
  };

  const pickFolder = async () => {
    setError("");
    try {
      const folder = await chooseFolder("Choose a folder of images");
      if (folder) await begin({ inputs: [folder], label: baseName(folder), base: baseName(folder) });
    } catch (reason) {
      setError(message(reason));
    }
  };

  const pickImages = async () => {
    setError("");
    try {
      const files = await chooseImages();
      if (!files || files.length === 0) return;
      const folder = baseName(parentPath(files[0]));
      const label = files.length === 1 ? baseName(files[0]) : `${files.length} selected images`;
      await begin({ inputs: files, label, base: folder });
    } catch (reason) {
      setError(message(reason));
    }
  };

  const changeResultsFolder = async () => {
    try {
      const folder = await chooseFolder("Choose where to save results");
      if (folder) setResultsParent(folder.replace(/\/+$/, ""));
    } catch (reason) {
      setError(message(reason));
    }
  };

  const count = async () => {
    if (!selection || !resultsParent) return;
    const root = `${resultsParent}/${selection.base} ${folderTimestamp(new Date())}`;
    setOutputRoot(root);
    setError("");
    setProgress({ done: 0, total: items.length });
    setPhase("counting");
    let counted = 0;
    try {
      await countSperm(selection.inputs, root, (event: CliEvent) => {
        if (event.event !== "image" || !event.summary || !event.overlay) return;
        const index = event.index - 1;
        counted += 1;
        updateItem(index, { overlay: event.overlay, summary: event.summary });
        setProgress({ done: event.index, total: event.total });
      });
      setPhase("done");
    } catch (reason) {
      setError(message(reason));
      setPhase(counted > 0 ? "done" : "ready");
    }
  };

  const go = useCallback(
    (index: number) => {
      if (items.length === 0) return;
      setCurrent((index + items.length) % items.length);
    },
    [items.length],
  );

  useEffect(() => {
    if (view !== "count" || items.length === 0) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        go(current - 1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        go(current + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, items.length, current, go]);

  // Keep the current thumbnail visible by scrolling the strip sideways only;
  // scrollIntoView would also scroll the whole page.
  useEffect(() => {
    const thumb = thumbRefs.current[current];
    const strip = thumb?.parentElement;
    if (!thumb || !strip) return;
    const thumbBox = thumb.getBoundingClientRect();
    const stripBox = strip.getBoundingClientRect();
    if (thumbBox.left < stripBox.left) strip.scrollLeft -= stripBox.left - thumbBox.left;
    else if (thumbBox.right > stripBox.right) strip.scrollLeft += thumbBox.right - stripBox.right;
  }, [current]);

  const item = items[current] as Item | undefined;
  const isCounted = Boolean(item?.summary);
  const mainPath = isCounted && showOverlay ? item?.overlay : item?.preview;

  const summaries = useMemo(() => items.flatMap((entry) => (entry.summary ? [entry.summary] : [])), [items]);
  const stats = useMemo(() => batchStats(summaries.map((summary) => summary.total_sperm)), [summaries]);
  const table = useMemo(() => countTable(summaries), [summaries]);

  const title =
    phase === "empty"
      ? "Count sperm"
      : phase === "done" && stats
        ? `${stats.total} sperm in ${plural(stats.images, "image")}`
        : `${plural(progress.total || items.length, "image")} to count`;

  const tag = isCounted
    ? showOverlay
      ? "Overlay"
      : "Original"
    : phase === "counting"
      ? "Original · counting…"
      : "Original";

  return (
    <div className={isDesktopShell() ? "desktop-root" : undefined}>
      <TitleBar />
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand-block">
            <div className="brand-mark">
              <img src={logo} alt="EyeSpySC logo" />
            </div>
            <div>
              <strong>EyeSpySC</strong>
              <span>Sperm counting, 20x</span>
            </div>
          </div>
          <nav aria-label="Primary navigation">
            <button
              type="button"
              className={view === "count" ? "nav-item active" : "nav-item"}
              aria-current={view === "count" ? "page" : undefined}
              onClick={() => setView("count")}
            >
              <span aria-hidden="true" className="nav-glyph">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="8.5" />
                  <path d="M10 8.5l5 3.5-5 3.5z" fill="currentColor" />
                </svg>
              </span>
              Count
            </button>
            <button
              type="button"
              className={view === "about" ? "nav-item active" : "nav-item"}
              aria-current={view === "about" ? "page" : undefined}
              onClick={() => setView("about")}
            >
              <span aria-hidden="true" className="nav-glyph">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                  <circle cx="12" cy="12" r="8.5" />
                  <path d="M12 11v5.5" />
                  <circle cx="12" cy="7.8" r="0.6" fill="currentColor" />
                </svg>
              </span>
              About
            </button>
          </nav>
          <div className="sidebar-foot">
            <span className="version-chip">{formatBuildLabel(APP_VERSION, BUILD_REVISION)}</span>
            <p>Local only. Images never leave this computer.</p>
          </div>
        </aside>

        <main className="main-content" id="main-content">
          {view === "count" ? (
            <div className="page-stack count-page">
              <header className="page-header">
                <div>
                  <p className="eyebrow">{selection ? selection.label : "New count"}</p>
                  <h1>{title}</h1>
                </div>
                {phase !== "empty" && (
                  <div className="page-header-actions">
                    <button className="button secondary" type="button" disabled={busy} onClick={() => void pickFolder()}>
                      Choose folder…
                    </button>
                    <button className="button secondary" type="button" disabled={busy} onClick={() => void pickImages()}>
                      Choose images…
                    </button>
                  </div>
                )}
              </header>

              {error && (
                <div className="inline-error" role="alert">
                  <strong>{phase === "empty" ? "Could not load the images" : "Something went wrong"}</strong>
                  <span>{error}</span>
                  <button type="button" aria-label="Dismiss" onClick={() => setError("")}>×</button>
                </div>
              )}

              {phase === "empty" ? (
                <section className="dropzone">
                  <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="6" y="10" width="36" height="28" rx="4" />
                    <circle cx="17" cy="20" r="3.5" />
                    <path d="M6 33l10-9 8 7 6-5 12 10" />
                  </svg>
                  <strong>Choose images to count</strong>
                  <p>
                    One image or a whole folder (subfolders included). You can look through
                    them before counting.
                  </p>
                  <p className="accepted-types">
                    Accepted files: {ACCEPTED_TYPES_TEXT}. 8- or 16-bit grayscale phase
                    contrast; color images are converted to gray.
                  </p>
                  <div className="dropzone-actions">
                    <button className="button primary" type="button" onClick={() => void pickFolder()}>
                      Choose folder…
                    </button>
                    <button className="button secondary" type="button" onClick={() => void pickImages()}>
                      Choose images…
                    </button>
                  </div>
                  <span className="fixed-note">
                    <b>20x</b> objective only, the one magnification EyeSpySC supports for now
                  </span>
                </section>
              ) : (
                <section className="panel workspace">
                  <div className="viewer">
                    <div className="viewer-head">
                      <button className="button secondary small" type="button" aria-label="Previous image" disabled={items.length < 2} onClick={() => go(current - 1)}>
                        ‹ Prev
                      </button>
                      <span className="viewer-position">
                        {items.length ? `Image ${current + 1} of ${items.length}` : "Loading…"}
                      </span>
                      <button className="button secondary small" type="button" aria-label="Next image" disabled={items.length < 2} onClick={() => go(current + 1)}>
                        Next ›
                      </button>
                      <span className="viewer-name" title={item?.image}>{item?.name ?? ""}</span>
                      {isCounted && (
                        <div className="segmented" role="group" aria-label="Image layer">
                          <button type="button" aria-pressed={showOverlay} onClick={() => setShowOverlay(true)}>Overlay</button>
                          <button type="button" aria-pressed={!showOverlay} onClick={() => setShowOverlay(false)}>Original</button>
                        </div>
                      )}
                    </div>
                    <div className="viewer-frame">
                      {mainPath && item ? (
                        <img
                          key={mainPath}
                          src={imageUrl(mainPath)}
                          alt={`${tag} of ${item.name}`}
                          onError={() => setError(`Could not show ${item.name}.`)}
                        />
                      ) : (
                        <div className="viewer-placeholder">Loading image…</div>
                      )}
                      {item && <span className="viewer-tag">{tag}</span>}
                    </div>
                    {isCounted && showOverlay && (
                      <ul className="color-key" aria-label="Overlay color key">
                        {COLOR_KEY.map(({ label, rgb, ring }) => (
                          <li key={label}>
                            <i
                              className={ring ? "swatch ring" : "swatch"}
                              style={ring ? { borderColor: `rgb(${rgb.join(",")})` } : { background: `rgb(${rgb.join(",")})` }}
                              aria-hidden="true"
                            />
                            {label}
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="filmstrip" role="group" aria-label="All images">
                      {items.map((entry, index) =>
                        entry ? (
                          <button
                            key={entry.image}
                            ref={(element) => {
                              thumbRefs.current[index] = element;
                            }}
                            type="button"
                            className="thumb"
                            aria-current={index === current}
                            aria-label={entry.summary ? `${entry.name}, ${entry.summary.total_sperm} sperm` : entry.name}
                            title={entry.name}
                            onClick={() => setCurrent(index)}
                          >
                            {entry.thumb ? (
                              <img src={imageUrl(entry.thumb)} alt="" loading="lazy" />
                            ) : (
                              <span className="thumb-empty" />
                            )}
                            {entry.summary && <b>{entry.summary.total_sperm}</b>}
                          </button>
                        ) : null,
                      )}
                    </div>
                  </div>

                  <aside className="side-panel">
                    {phase === "loading" && (
                      <section>
                        <h2 className="side-heading">Loading images</h2>
                        <div className="progress" aria-hidden="true">
                          <i style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }} />
                        </div>
                        <p className="run-status" role="status">
                          {progress.total ? `${progress.done} of ${progress.total} loaded` : "Finding images…"}
                        </p>
                      </section>
                    )}

                    {(phase === "ready" || phase === "counting") && (
                      <>
                        <section>
                          <h2 className="side-heading">Ready to count</h2>
                          <div className="kv"><span>Images</span><b>{items.length}</b></div>
                          <div className="kv"><span>Objective</span><b>20x (fixed)</b></div>
                          <div className="kv">
                            <span>Results saved to</span>
                            <button className="text-button" type="button" disabled={busy} onClick={() => void changeResultsFolder()}>
                              Change…
                            </button>
                          </div>
                          <div className="path-box">
                            {outputRoot || `${resultsParent}/${selection?.base ?? ""} (date and time)`}
                          </div>
                        </section>
                        <section>
                          <button className="button primary large count-button" type="button" disabled={busy || !resultsParent || items.length === 0} onClick={() => void count()}>
                            {phase === "counting" ? "Counting…" : "Count sperm"}
                          </button>
                          {phase === "counting" && (
                            <div className="progress" aria-hidden="true">
                              <i style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }} />
                            </div>
                          )}
                          <p className="run-status" role="status">
                            {phase === "counting"
                              ? `Counted ${progress.done} of ${progress.total}`
                              : "Look through the images first if you like."}
                          </p>
                        </section>
                      </>
                    )}

                    {phase === "done" && (
                      <>
                        <section>
                          <h2 className="side-heading">This image</h2>
                          {item?.summary && stats ? (
                            <>
                              <div className="big-count">
                                <strong>{item.summary.total_sperm}</strong>
                                <span>total sperm</span>
                              </div>
                              <p className="count-rule">Intact + the larger of tail-less and head-less</p>
                              <div className="kv"><span>Intact</span><b>{item.summary.intact}</b></div>
                              <div className="kv"><span>Tail-less</span><b>{item.summary.tailless}</b></div>
                              <div className="kv"><span>Head-less</span><b>{item.summary.headless}</b></div>
                              <div className="kv kv-gap"><span>Total heads</span><b>{item.summary.total_heads}</b></div>
                              <div className="kv"><span>Total tails</span><b>{item.summary.total_tails}</b></div>
                              <div className="kv"><span>Barely visible, not in total</span><b>{item.summary.barely_visible}</b></div>
                              <p className="versus">{compareToMean(item.summary.total_sperm, stats.mean)}</p>
                            </>
                          ) : (
                            <p className="run-status">Not counted.</p>
                          )}
                        </section>
                        {stats && (
                          <section>
                            <h2 className="side-heading">
                              {stats.images === items.length ? `All ${plural(stats.images, "image")}` : `${stats.images} of ${items.length} images`}
                            </h2>
                            <table className="batch-table">
                              <thead>
                                <tr>
                                  <th scope="col"><span className="visually-hidden">Count</span></th>
                                  <th scope="col">Total</th>
                                  <th scope="col">Mean</th>
                                  <th scope="col">Median</th>
                                  <th scope="col">Range</th>
                                </tr>
                              </thead>
                              <tbody>
                                {table.map(({ key, label, stats: row }) => (
                                  <tr key={key} className={key === "total_sperm" ? "lead" : undefined}>
                                    <th scope="row">{label}</th>
                                    <td>{row.total}</td>
                                    <td>{formatNumber(row.mean)}</td>
                                    <td>{formatNumber(row.median)}</td>
                                    <td>{row.min}–{row.max}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </section>
                        )}
                        <section>
                          <p className="saved-note">
                            Saved <code>summary.csv</code>, <code>batch_stats.csv</code> and every overlay to <code>{outputRoot}</code>
                          </p>
                          <button className="button secondary small" type="button" onClick={() => void openDirectory(outputRoot).catch((reason) => setError(message(reason)))}>
                            Open results folder
                          </button>
                        </section>
                      </>
                    )}
                  </aside>
                </section>
              )}
            </div>
          ) : (
            <div className="page-stack">
              <div className="about">
                <div className="about-logo">
                  <img src={logo} alt="EyeSpySC logo" />
                </div>
                <div className="panel">
                  <p className="eyebrow">About</p>
                  <h1>EyeSpySC</h1>
                  <p className="lede">
                    Counts sperm in low-contrast grayscale 20x phase-contrast images using
                    deterministic image processing. No model training, no network access.
                  </p>
                  <dl>
                    <dt>Version</dt>
                    <dd>{formatBuildLabel(APP_VERSION, BUILD_REVISION)}</dd>
                    <dt>Counting engine</dt>
                    <dd>The bundled <code>eyespysc</code> command, also usable in a terminal</dd>
                    <dt>License</dt>
                    <dd>MIT · Yan Lab</dd>
                  </dl>
                  <ul>
                    <li>Counts are provisional until checked against expert counts.</li>
                    <li>Only 20x images are supported. Extremely crowded frames are out of scope.</li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
