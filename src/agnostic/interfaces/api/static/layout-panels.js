import React from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { PainelOrientacao } from "/static/components/PainelOrientacao.js?v=orientation-v4";
import { QuadroColecaoCards } from "/static/components/QuadroColecaoCards.js?v=collection-v15";
import { createExplorationProgressState } from "/static/components/explorationProgressState.js";

const STATE_REFERENCE_MIME = "application/x-agnostic-state-reference";
const EXPLORATION_STATE_VERSION = "v2";

function normalizeNodeKey(rawValue) {
  const value = String(rawValue || "").trim();
  if (!value) return "";
  try {
    const url = new URL(value, window.location.origin);
    return `${url.pathname}${url.search || ""}`;
  } catch {
    return value;
  }
}

function parsePanelsPayload() {
  const node = document.getElementById("left-functional-panels-data");
  if (!node || !node.textContent) return null;

  try {
    return JSON.parse(node.textContent);
  } catch (error) {
    console.error("Falha ao carregar payload dos painéis funcionais.", error);
    return null;
  }
}

function parseCollectionPayload() {
  const node = document.getElementById("collection-board-data");
  if (!node || !node.textContent) return null;
  try {
    return JSON.parse(node.textContent);
  } catch (error) {
    console.error("Falha ao carregar payload do quadro de colecao.", error);
    return null;
  }
}

function collectionStorageKey(sessionKey) {
  return `agnostic-collection-cards:${sessionKey || "default"}`;
}

function nodeProgressStorageKey(sessionKey) {
  return `agnostic-node-progress:${sessionKey || "default"}:${EXPLORATION_STATE_VERSION}`;
}

function nodeStarsStorageKey(sessionKey) {
  return `agnostic-node-stars:${sessionKey || "default"}:${EXPLORATION_STATE_VERSION}`;
}

function readCollectionCards(sessionKey) {
  try {
    const raw = localStorage.getItem(collectionStorageKey(sessionKey));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeCollectionCards(sessionKey, cards) {
  try {
    localStorage.setItem(collectionStorageKey(sessionKey), JSON.stringify(cards));
  } catch {
    // no-op
  }
}

function readNodeProgressMap(sessionKey) {
  try {
    const raw = localStorage.getItem(nodeProgressStorageKey(sessionKey));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeNodeProgressMap(sessionKey, map) {
  try {
    localStorage.setItem(nodeProgressStorageKey(sessionKey), JSON.stringify(map || {}));
  } catch {
    // no-op
  }
}

function readNodeStarsMap(sessionKey) {
  try {
    const raw = localStorage.getItem(nodeStarsStorageKey(sessionKey));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeNodeStarsMap(sessionKey, map) {
  try {
    localStorage.setItem(nodeStarsStorageKey(sessionKey), JSON.stringify(map || {}));
  } catch {
    // no-op
  }
}

function addCardToCollection(sessionKey, payload) {
  const cards = readCollectionCards(sessionKey);
  const href = payload?.state_reference?.href || "";
  if (!href) return false;
  const alreadyExists = cards.some((item) => item?.state_reference?.href === href);
  if (alreadyExists) return false;
  const next = [
    ...cards,
    {
      id: (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : `card-${Date.now()}`,
      label: payload.label || "Estado",
      state_reference: payload.state_reference,
      summary_line: typeof payload.summary_line === "string" ? payload.summary_line : "",
      position: cards.length + 1,
    },
  ];
  writeCollectionCards(sessionKey, next);
  window.dispatchEvent(new CustomEvent("agnostic:collection-updated", { detail: { sessionKey } }));
  return true;
}

function extractCardSummaryLine(ownerCard) {
  if (!(ownerCard instanceof Element)) return "";
  const explicitSummary = String(ownerCard.getAttribute("data-summary-line") || "").trim();
  if (explicitSummary) return explicitSummary;
  const lines = String(ownerCard.innerText || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  return lines[1] || "";
}

function normalizeProgressFill(header, exploration) {
  const fill = header.querySelector(".card-head-progress-fill");
  if (!fill) return;
  const safe = Math.max(0, Math.min(1, Number(exploration) || 0));
  fill.style.width = `${(safe * 100).toFixed(2)}%`;
  if (safe >= 1) {
    fill.style.backgroundColor = "#1d4ed8"; // concluído (azul forte)
  } else if (safe > 0) {
    fill.style.backgroundColor = "#3b82f6"; // em progresso (azul médio)
  } else {
    fill.style.backgroundColor = "#93c5fd"; // não visto (azul claro)
  }
}

function normalizeStars(header, stars) {
  const starsNode = header?.querySelector(".card-head-stars");
  if (!starsNode) return;
  const safe = Math.max(0, Math.min(10, Number(stars) || 0));
  starsNode.textContent = safe > 0 ? "★".repeat(safe) : "";
  starsNode.setAttribute("aria-label", safe > 0 ? `${safe} estrela(s)` : "sem estrelas");
  if (safe > 0) {
    starsNode.removeAttribute("hidden");
  } else {
    starsNode.setAttribute("hidden", "");
  }
}

function installCardHeaderActions(collectionPayload) {
  const sessionKey = collectionPayload?.sessionKey || "default";
  const progressKey = `agnostic-exploration-progress:${sessionKey}:${EXPLORATION_STATE_VERSION}`;
  const seenCardsKey = `agnostic-seen-cards:${sessionKey}:${EXPLORATION_STATE_VERSION}`;
  const starredCardsKey = `agnostic-starred-cards:${sessionKey}:${EXPLORATION_STATE_VERSION}`;
  const currentNodeKey = normalizeNodeKey(window.location.href);
  let initialProgress = null;
  try {
    const raw = sessionStorage.getItem(progressKey);
    initialProgress = raw ? JSON.parse(raw) : null;
  } catch {
    initialProgress = null;
  }
  const progress = createExplorationProgressState(initialProgress || undefined);
  progress.register_node(currentNodeKey, true);

  let seenCards = new Set();
  try {
    const raw = sessionStorage.getItem(seenCardsKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      seenCards = new Set(parsed.map((item) => String(item || "")));
    }
  } catch {
    seenCards = new Set();
  }
  let nodeProgressMap = readNodeProgressMap(sessionKey);
  let starredCards = new Set();
  try {
    const raw = sessionStorage.getItem(starredCardsKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) {
      starredCards = new Set(parsed.map((item) => String(item || "")));
    }
  } catch {
    starredCards = new Set();
  }
  let nodeStarsMap = readNodeStarsMap(sessionKey);

  const headers = Array.from(document.querySelectorAll(".card-head-row"));
  headers.forEach((header, index) => {
    const ownerLink = header.closest("a.metric-link");
    const ownerCard = header.closest(".metric-card, .focus-column-card, .focus-stat-card, .collection-card, article, section, div");
    const href = ownerLink?.getAttribute("href") || "";
    const normalizedHref = normalizeNodeKey(href);
    const cardKey = normalizedHref || `card-local-${index}`;
    const seenKey = normalizedHref || cardKey;
    const starKey = normalizedHref || cardKey;
    progress.register_card(cardKey, currentNodeKey);

    const persistedNodeRatio = Number(nodeProgressMap[cardKey] || 0);
    const derivedNodeExploration = progress.compute_node_exploration(cardKey);
    const isSeen = seenCards.has(seenKey);
    if (isSeen) {
      progress.mark_card_opened(cardKey);
      progress.set_generated_children_count(cardKey, 1);
      progress.set_explored_children_count(cardKey, 1);
      normalizeProgressFill(header, 1.0);
      if (ownerCard) ownerCard.setAttribute("data-seen", "true");
      const seenAction = header.querySelector(".card-head-action[data-card-action='mark-seen']");
      if (seenAction) seenAction.setAttribute("data-active", "true");
    } else if (persistedNodeRatio > 0) {
      progress.mark_card_opened(cardKey);
      progress.set_generated_children_count(cardKey, 100);
      progress.set_explored_children_count(cardKey, Math.round(persistedNodeRatio * 100));
      normalizeProgressFill(header, persistedNodeRatio);
    } else if (derivedNodeExploration > 0) {
      progress.mark_card_opened(cardKey);
      progress.set_generated_children_count(cardKey, 100);
      progress.set_explored_children_count(cardKey, Math.round(derivedNodeExploration * 100));
      normalizeProgressFill(header, derivedNodeExploration);
    } else {
      progress.set_generated_children_count(cardKey, 100);
      progress.set_explored_children_count(cardKey, 0);
      normalizeProgressFill(header, 0);
    }

    if (ownerCard) ownerCard.setAttribute("data-card-key", cardKey);
    header.setAttribute("data-card-key", cardKey);

    const isStarred = starredCards.has(starKey);
    const starAction = header.querySelector(".card-head-action[data-card-action='star']");
    if (starAction) {
      if (isStarred) starAction.setAttribute("data-active", "true");
      else starAction.removeAttribute("data-active");
    }
    const childStars = Math.max(0, Math.min(10, Number(nodeStarsMap[cardKey] || 0)));
    normalizeStars(header, (isStarred ? 1 : 0) + childStars);
  });

  function persistCurrentNodeProgress() {
    const cardHeaders = Array.from(document.querySelectorAll(".card-head-row[data-card-key]"));
    if (cardHeaders.length === 0) return;
    let explored = 0;
    for (const header of cardHeaders) {
      const fill = header.querySelector(".card-head-progress-fill");
      const width = fill?.style?.width || "";
      const pct = Number(String(width).replace("%", ""));
      const ratio = Number.isFinite(pct) ? Math.max(0, Math.min(1, pct / 100)) : 0;
      explored += ratio;
    }
    const nodeRatio = Math.max(0, Math.min(1, explored / cardHeaders.length));
    nodeProgressMap[currentNodeKey] = nodeRatio;
    writeNodeProgressMap(sessionKey, nodeProgressMap);
    window.dispatchEvent(new CustomEvent("agnostic:progress-updated", { detail: { sessionKey } }));
  }

  function persistCurrentNodeStars() {
    const cardHeaders = Array.from(document.querySelectorAll(".card-head-row[data-card-key]"));
    if (cardHeaders.length === 0) return;
    let starred = 0;
    for (const header of cardHeaders) {
      const starAction = header.querySelector(".card-head-action[data-card-action='star']");
      if (starAction?.getAttribute("data-active") === "true") starred += 1;
    }
    nodeStarsMap[currentNodeKey] = Math.max(0, Math.min(10, starred));
    writeNodeStarsMap(sessionKey, nodeStarsMap);
    window.dispatchEvent(new CustomEvent("agnostic:stars-updated", { detail: { sessionKey } }));
  }

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest(".card-head-action[data-card-action]") : null;
    if (!target) return;
    const action = target.getAttribute("data-card-action") || "";
    const header = target.closest(".card-head-row");
    const ownerLink = target.closest("a.metric-link");
    const ownerCard = target.closest(".metric-card, .focus-column-card, .focus-stat-card");
    const cardKey = header?.getAttribute("data-card-key") || ownerCard?.getAttribute("data-card-key") || "";

    event.preventDefault();
    event.stopPropagation();

    if (action === "add-to-collection") {
      const title = header?.querySelector(".card-head-title")?.textContent?.trim() || "Estado";
      const href = ownerLink?.getAttribute("href") || "";
      const normalizedHref = normalizeNodeKey(href);
      const summaryLine = extractCardSummaryLine(ownerCard);
      const added = addCardToCollection(sessionKey, {
        label: title,
        summary_line: summaryLine,
        state_reference: {
          href: normalizedHref,
          node_id: cardKey,
          layer: "card",
        },
      });
      if (added) target.setAttribute("data-active", "true");
      return;
    }

    if (action === "mark-seen" && cardKey) {
      const href = ownerLink?.getAttribute("href") || "";
      const normalizedHref = normalizeNodeKey(href);
      const seenKey = normalizedHref || cardKey;
      const currentlySeen = seenCards.has(seenKey);

      if (currentlySeen) {
        seenCards.delete(seenKey);
        const restored = Math.max(0, Math.min(1, Number(nodeProgressMap[cardKey] || 0)));
        progress.mark_card_opened(cardKey);
        progress.set_generated_children_count(cardKey, 100);
        progress.set_explored_children_count(cardKey, Math.round(restored * 100));
        if (header) normalizeProgressFill(header, restored);
        if (ownerCard) {
          if (restored >= 1.0) {
            ownerCard.setAttribute("data-seen", "true");
          } else {
            ownerCard.removeAttribute("data-seen");
          }
        }
        target.removeAttribute("data-active");
      } else {
        progress.mark_card_opened(cardKey);
        progress.set_generated_children_count(cardKey, 1);
        progress.set_explored_children_count(cardKey, 1);
        if (header) normalizeProgressFill(header, 1.0);
        if (ownerCard) ownerCard.setAttribute("data-seen", "true");
        seenCards.add(seenKey);
        target.setAttribute("data-active", "true");
      }

      try {
        sessionStorage.setItem(seenCardsKey, JSON.stringify([...seenCards]));
      } catch {
        // no-op
      }
      try {
        sessionStorage.setItem(progressKey, JSON.stringify(progress.snapshot()));
      } catch {
        // no-op
      }
      persistCurrentNodeProgress();
      persistCurrentNodeStars();
      return;
    }

    if (action === "star" && cardKey) {
      const href = ownerLink?.getAttribute("href") || "";
      const normalizedHref = normalizeNodeKey(href);
      const starKey = normalizedHref || cardKey;
      const currentlyStarred = starredCards.has(starKey);

      if (currentlyStarred) {
        starredCards.delete(starKey);
        target.removeAttribute("data-active");
      } else {
        starredCards.add(starKey);
        target.setAttribute("data-active", "true");
      }

      if (header) {
        const childStars = Math.max(0, Math.min(10, Number(nodeStarsMap[cardKey] || 0)));
        normalizeStars(header, (currentlyStarred ? 0 : 1) + childStars);
      }

      try {
        sessionStorage.setItem(starredCardsKey, JSON.stringify([...starredCards]));
      } catch {
        // no-op
      }
      persistCurrentNodeStars();
      return;
    }
  });

  persistCurrentNodeProgress();
  persistCurrentNodeStars();
}

function LeftFunctionalPanels({ payload, collectionPayload }) {
  return React.createElement(
    React.Fragment,
    null,
    React.createElement(PainelOrientacao, {
      title: payload.orientationTitle || "Histórico de orientação",
      data: payload.orientationData || null,
      graph: payload.orientationGraph || null,
    }),
    collectionPayload
      ? React.createElement(QuadroColecaoCards, {
          payload: collectionPayload,
        })
      : null,
  );
}

function installStateReferenceDragBridge() {
  document.addEventListener("dragstart", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-state-href]") : null;
    if (!target || !event.dataTransfer) return;
    const href = target.getAttribute("data-state-href") || "";
    if (!href) return;
    const payload = JSON.stringify({
      label: target.getAttribute("data-state-label") || target.textContent?.trim() || "Estado",
      state_reference: {
        href,
        node_id: target.getAttribute("data-state-node-id") || "",
        layer: target.getAttribute("data-state-layer") || "origem",
      },
    });
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(STATE_REFERENCE_MIME, payload);
    event.dataTransfer.setData("text/plain", payload);
  });
}

const rootNode = document.getElementById("left-functional-panels-root");
const payload = parsePanelsPayload();
const collectionPayload = parseCollectionPayload();
installStateReferenceDragBridge();
installCardHeaderActions(collectionPayload);

if (rootNode && payload) {
  const root = createRoot(rootNode);
  root.render(React.createElement(LeftFunctionalPanels, { payload, collectionPayload }));
  const fallback = document.getElementById("collection-board-fallback");
  if (fallback) fallback.setAttribute("hidden", "");
}
