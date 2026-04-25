import React from "https://esm.sh/react@18.3.1";
const CARD_INDEX_MIME = "application/x-agnostic-collection-card-index";
const STATE_REFERENCE_MIME = "application/x-agnostic-state-reference";
const EXPLORATION_STATE_VERSION = "v2";

function storageKey(sessionKey) {
  return `agnostic-collection-cards:${sessionKey || "default"}`;
}

function nodeStarsStorageKey(sessionKey) {
  return `agnostic-node-stars:${sessionKey || "default"}:${EXPLORATION_STATE_VERSION}`;
}

function nodeProgressStorageKey(sessionKey) {
  return `agnostic-node-progress:${sessionKey || "default"}:${EXPLORATION_STATE_VERSION}`;
}

function starredCardsStorageKey(sessionKey) {
  return `agnostic-starred-cards:${sessionKey || "default"}:${EXPLORATION_STATE_VERSION}`;
}

function generateId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `card-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

function normalizeCards(rawCards) {
  if (!Array.isArray(rawCards)) return [];
  const normalized = rawCards
    .filter((item) => item && typeof item === "object")
    .map((item, index) => ({
      id: typeof item.id === "string" && item.id.trim() ? item.id : generateId(),
      state_reference: item.state_reference && typeof item.state_reference === "object" ? item.state_reference : {},
      label: typeof item.label === "string" && item.label.trim() ? item.label.trim() : `Card ${index + 1}`,
      summary_line: typeof item.summary_line === "string" ? item.summary_line.trim() : "",
      position: Number.isFinite(Number(item.position)) ? Number(item.position) : index + 1,
    }))
    .sort((a, b) => a.position - b.position);

  return normalized.map((card, index) => ({ ...card, position: index + 1 }));
}

function loadCards(sessionKey) {
  try {
    const raw = localStorage.getItem(storageKey(sessionKey));
    if (!raw) return [];
    return normalizeCards(JSON.parse(raw));
  } catch {
    return [];
  }
}

function persistCards(sessionKey, cards) {
  const normalized = normalizeCards(cards);
  localStorage.setItem(storageKey(sessionKey), JSON.stringify(normalized));
  return normalized;
}

function moveCard(cards, fromIndex, toIndex) {
  if (fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= cards.length || toIndex >= cards.length) {
    return cards;
  }
  const next = [...cards];
  const [item] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, item);
  return next.map((card, index) => ({ ...card, position: index + 1 }));
}

function parseStateReferenceFromDrop(event) {
  const raw = event.dataTransfer.getData(STATE_REFERENCE_MIME) || event.dataTransfer.getData("text/plain");
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    if (!parsed.state_reference || typeof parsed.state_reference !== "object") return null;
    const href = parsed.state_reference.href;
    if (typeof href !== "string" || !href.trim()) return null;
    return {
      label: typeof parsed.label === "string" && parsed.label.trim() ? parsed.label.trim() : "Estado",
      state_reference: parsed.state_reference,
    };
  } catch {
    return null;
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

function readStarredCards(sessionKey) {
  try {
    const raw = sessionStorage.getItem(starredCardsStorageKey(sessionKey));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? new Set(parsed.map((item) => String(item || ""))) : new Set();
  } catch {
    return new Set();
  }
}

function classifyCard(card) {
  const href = String(card?.state_reference?.href || "");
  try {
    const url = new URL(href, window.location.origin);
    const action = (url.searchParams.get("action") || "").toLowerCase();
    const column = url.searchParams.get("column_name") || "";
    if (action === "coluna" || column) return "Coluna";
    if (action === "tabela" || action === "quick") return "Tabela";
    if (action === "slice") return "Recorte";
    return "Estado";
  } catch {
    return "Estado";
  }
}

function buildStarsLabel(stars) {
  const safe = Math.max(0, Math.min(10, Number(stars) || 0));
  if (safe <= 0) return "";
  return "★".repeat(safe);
}

function CardItem({ card, index, onOpen, onMove, onRemoveByDragOut, stars, progress }) {
  const cardKind = classifyCard(card);
  const starsLabel = buildStarsLabel(stars);
  const safeProgress = Math.max(0, Math.min(1, Number(progress) || 0));
  const summaryLine = String(card?.summary_line || "").trim();
  return React.createElement(
    "article",
    {
      className: "collection-card",
      role: "button",
      tabIndex: 0,
      draggable: true,
      onClick: () => onOpen(card),
      onKeyDown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(card);
        }
      },
      onDragStart: (event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData(CARD_INDEX_MIME, String(index));
        event.dataTransfer.setData("text/plain", String(index));
      },
      onDragEnd: (event) => {
        const effect = String(event?.dataTransfer?.dropEffect || "").toLowerCase();
        if (effect === "none") {
          onRemoveByDragOut(card.id);
        }
      },
      onDragOver: (event) => event.preventDefault(),
      onDrop: (event) => {
        event.preventDefault();
        const from = Number(event.dataTransfer.getData(CARD_INDEX_MIME) || event.dataTransfer.getData("text/plain"));
        if (Number.isFinite(from)) onMove(from, index);
      },
    },
    React.createElement(
      "div",
      { className: "collection-card-meta" },
      cardKind,
    ),
    React.createElement(
      "div",
      { className: "collection-card-title" },
      card.label,
    ),
    React.createElement(
      "div",
      { className: "collection-card-progress-row" },
      React.createElement(
        "span",
        { className: "collection-card-progress", "aria-hidden": "true" },
        React.createElement("span", {
          className: "collection-card-progress-fill",
          style: { width: `${(safeProgress * 100).toFixed(2)}%` },
        }),
      ),
      starsLabel
        ? React.createElement("div", { className: "collection-card-stars", "aria-label": `${stars} estrela(s)` }, starsLabel)
        : React.createElement("div", { className: "collection-card-stars", hidden: true }, ""),
    ),
    (summaryLine && cardKind !== "Tabela")
      ? React.createElement("div", { className: "collection-card-hint" }, summaryLine)
      : null,
  );
}

export function QuadroColecaoCards({ payload }) {
  const sessionKey = payload?.sessionKey || "default";
  const [cards, setCards] = React.useState(() => loadCards(sessionKey));
  const [nodeStarsMap, setNodeStarsMap] = React.useState(() => readNodeStarsMap(sessionKey));
  const [nodeProgressMap, setNodeProgressMap] = React.useState(() => readNodeProgressMap(sessionKey));
  const [starredCards, setStarredCards] = React.useState(() => readStarredCards(sessionKey));

  React.useEffect(() => {
    setCards(loadCards(sessionKey));
    setNodeStarsMap(readNodeStarsMap(sessionKey));
    setNodeProgressMap(readNodeProgressMap(sessionKey));
    setStarredCards(readStarredCards(sessionKey));
  }, [sessionKey]);

  React.useEffect(() => {
    function handleCollectionUpdate(event) {
      const targetSessionKey = event?.detail?.sessionKey || "default";
      if (String(targetSessionKey) !== String(sessionKey)) return;
      setCards(loadCards(sessionKey));
      setNodeStarsMap(readNodeStarsMap(sessionKey));
      setNodeProgressMap(readNodeProgressMap(sessionKey));
      setStarredCards(readStarredCards(sessionKey));
    }

    function handleStorage(event) {
      if (!event?.key) return;
      if (event.key === storageKey(sessionKey)) {
        setCards(loadCards(sessionKey));
      }
      if (event.key === nodeStarsStorageKey(sessionKey)) {
        setNodeStarsMap(readNodeStarsMap(sessionKey));
      }
      if (event.key === nodeProgressStorageKey(sessionKey)) {
        setNodeProgressMap(readNodeProgressMap(sessionKey));
      }
    }

    function handleProgressUpdate(event) {
      const targetSessionKey = event?.detail?.sessionKey || "default";
      if (String(targetSessionKey) !== String(sessionKey)) return;
      setNodeProgressMap(readNodeProgressMap(sessionKey));
    }

    function handleStarsUpdate(event) {
      const targetSessionKey = event?.detail?.sessionKey || "default";
      if (String(targetSessionKey) !== String(sessionKey)) return;
      setNodeStarsMap(readNodeStarsMap(sessionKey));
      setStarredCards(readStarredCards(sessionKey));
    }

    window.addEventListener("agnostic:collection-updated", handleCollectionUpdate);
    window.addEventListener("storage", handleStorage);
    window.addEventListener("agnostic:progress-updated", handleProgressUpdate);
    window.addEventListener("agnostic:stars-updated", handleStarsUpdate);
    return () => {
      window.removeEventListener("agnostic:collection-updated", handleCollectionUpdate);
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("agnostic:progress-updated", handleProgressUpdate);
      window.removeEventListener("agnostic:stars-updated", handleStarsUpdate);
    };
  }, [sessionKey]);

  const handleAddStateReference = React.useCallback(
    (statePayload) => {
      setCards((previous) => {
        const next = [
          ...previous,
          {
            id: generateId(),
            state_reference: statePayload.state_reference,
            label: statePayload.label,
            position: previous.length + 1,
          },
        ];
        const persisted = persistCards(sessionKey, next);
        return persisted;
      });
    },
    [sessionKey],
  );

  const handleMove = React.useCallback(
    (fromIndex, toIndex) => {
      setCards((previous) => {
        const moved = moveCard(previous, fromIndex, toIndex);
        const persisted = persistCards(sessionKey, moved);
        return persisted;
      });
    },
    [sessionKey],
  );

  const handleRemoveByDragOut = React.useCallback(
    (cardId) => {
      if (!cardId) return;
      setCards((previous) => {
        const next = previous.filter((card) => card.id !== cardId).map((card, idx) => ({ ...card, position: idx + 1 }));
        return persistCards(sessionKey, next);
      });
    },
    [sessionKey],
  );

  const handleOpen = React.useCallback((card) => {
    const href = card?.state_reference?.href;
    if (!href) return;
    window.location.href = href;
  }, []);

  const handleBoardDrop = React.useCallback(
    (event) => {
      event.preventDefault();
      const fromIndex = Number(event.dataTransfer.getData(CARD_INDEX_MIME) || event.dataTransfer.getData("text/plain"));
      if (Number.isFinite(fromIndex) && cards.length > 0) {
        handleMove(fromIndex, cards.length - 1);
        return;
      }
      const droppedState = parseStateReferenceFromDrop(event);
      if (droppedState) {
        handleAddStateReference(droppedState);
      }
    },
    [cards.length, handleMove, handleAddStateReference],
  );

  return React.createElement(
    "section",
    {
      className: "functional-panel collection-board",
      "aria-label": "Quadro de colecao",
      onDragOver: (event) => event.preventDefault(),
      onDrop: handleBoardDrop,
    },
    React.createElement("div", { className: "results-title" }, "Quadro de colecao"),
    React.createElement(
      "div",
      { className: "collection-card-list" },
      cards.map((card, index) =>
        React.createElement(CardItem, {
          key: card.id,
          card,
          index,
          stars: Math.max(
            0,
            Math.min(
              10,
              Number(nodeStarsMap[String(card?.state_reference?.href || "")] || 0)
                + (starredCards.has(String(card?.state_reference?.href || "")) ? 1 : 0),
            ),
          ),
          progress: Math.max(0, Math.min(1, Number(nodeProgressMap[String(card?.state_reference?.href || "")] || 0))),
          onOpen: handleOpen,
          onMove: handleMove,
          onRemoveByDragOut: handleRemoveByDragOut,
        }),
      ),
    ),
  );
}
