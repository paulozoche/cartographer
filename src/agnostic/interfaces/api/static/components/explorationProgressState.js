function clamp01(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function toNonNegativeInt(value) {
  if (!Number.isFinite(Number(value))) return 0;
  return Math.max(0, Math.trunc(Number(value)));
}

function sanitizeCardState(card) {
  const generated = toNonNegativeInt(card?.generated_children_count);
  const explored = toNonNegativeInt(card?.explored_children_count);
  return {
    card_key: String(card?.card_key || ""),
    parent_node_key: String(card?.parent_node_key || ""),
    opened: Boolean(card?.opened),
    generated_children_count: generated,
    explored_children_count: explored,
  };
}

export function compute_card_exploration(cardState) {
  const card = sanitizeCardState(cardState);
  if (!card.opened) return 0.0;
  if (card.generated_children_count === 0) return 1.0;
  return clamp01(card.explored_children_count / card.generated_children_count);
}

function ensureNode(store, nodeKey) {
  const key = String(nodeKey || "");
  if (!key) return null;
  if (!store.nodes[key]) {
    store.nodes[key] = {
      node_key: key,
      opened: false,
      cards: [],
    };
  }
  return store.nodes[key];
}

function ensureCard(store, cardKey) {
  const key = String(cardKey || "");
  if (!key) return null;
  if (!store.cards[key]) {
    store.cards[key] = sanitizeCardState({
      card_key: key,
      parent_node_key: "",
      opened: false,
      generated_children_count: 0,
      explored_children_count: 0,
    });
  }
  return store.cards[key];
}

function linkCardToNode(store, cardKey, nodeKey) {
  const node = ensureNode(store, nodeKey);
  const card = ensureCard(store, cardKey);
  if (!node || !card) return;

  if (card.parent_node_key && card.parent_node_key !== node.node_key) {
    const previousNode = store.nodes[card.parent_node_key];
    if (previousNode) {
      previousNode.cards = previousNode.cards.filter((key) => key !== card.card_key);
    }
  }

  card.parent_node_key = node.node_key;
  if (!node.cards.includes(card.card_key)) {
    node.cards.push(card.card_key);
  }
}

function computeNodeExplorationFromStore(store, nodeKey) {
  const node = store.nodes[String(nodeKey || "")];
  if (!node) return 0.0;

  const cardStates = node.cards
    .map((cardKey) => store.cards[cardKey])
    .filter((card) => Boolean(card));

  if (cardStates.length === 0) {
    return node.opened ? 1.0 : 0.0;
  }

  const total = cardStates.reduce((acc, card) => acc + compute_card_exploration(card), 0);
  return clamp01(total / cardStates.length);
}

function computeNodeSummaryFromStore(store, nodeKey) {
  const node = store.nodes[String(nodeKey || "")];
  if (!node) {
    return {
      total_cards: 0,
      opened_cards: 0,
      fully_explored_cards: 0,
      partially_explored_cards: 0,
      node_exploration: 0.0,
    };
  }

  const cardStates = node.cards
    .map((cardKey) => store.cards[cardKey])
    .filter((card) => Boolean(card));

  let openedCards = 0;
  let fullyExplored = 0;
  let partiallyExplored = 0;

  for (const card of cardStates) {
    const exploration = compute_card_exploration(card);
    if (card.opened) openedCards += 1;
    if (exploration >= 1.0) {
      fullyExplored += 1;
    } else if (exploration > 0.0) {
      partiallyExplored += 1;
    }
  }

  return {
    total_cards: cardStates.length,
    opened_cards: openedCards,
    fully_explored_cards: fullyExplored,
    partially_explored_cards: partiallyExplored,
    node_exploration: computeNodeExplorationFromStore(store, nodeKey),
  };
}

function ensureStateShape(state) {
  if (!state || typeof state !== "object") {
    return { nodes: {}, cards: {} };
  }
  if (!state.nodes || typeof state.nodes !== "object") state.nodes = {};
  if (!state.cards || typeof state.cards !== "object") state.cards = {};
  return state;
}

export function mark_card_opened(state, card_key) {
  const safeState = ensureStateShape(state);
  const card = ensureCard(safeState, card_key);
  if (!card) return;
  card.opened = true;
}

export function set_generated_children_count(state, card_key, count) {
  const safeState = ensureStateShape(state);
  const card = ensureCard(safeState, card_key);
  if (!card) return;
  card.generated_children_count = toNonNegativeInt(count);
}

export function set_explored_children_count(state, card_key, count) {
  const safeState = ensureStateShape(state);
  const card = ensureCard(safeState, card_key);
  if (!card) return;
  card.explored_children_count = toNonNegativeInt(count);
}

export function compute_node_exploration(state, node_key) {
  const safeState = ensureStateShape(state);
  return computeNodeExplorationFromStore(safeState, node_key);
}

export function compute_exploration_summary(state, node_key) {
  const safeState = ensureStateShape(state);
  return computeNodeSummaryFromStore(safeState, node_key);
}

export function createExplorationProgressState(initialState = {}) {
  const store = {
    nodes: {},
    cards: {},
  };

  const initialNodes = Array.isArray(initialState.nodes) ? initialState.nodes : [];
  for (const rawNode of initialNodes) {
    const node = ensureNode(store, rawNode?.node_key);
    if (!node) continue;
    node.opened = Boolean(rawNode?.opened);
  }

  const initialCards = Array.isArray(initialState.cards) ? initialState.cards : [];
  for (const rawCard of initialCards) {
    const card = sanitizeCardState(rawCard);
    if (!card.card_key) continue;
    ensureCard(store, card.card_key);
    store.cards[card.card_key] = card;
    if (card.parent_node_key) {
      linkCardToNode(store, card.card_key, card.parent_node_key);
    }
  }

  return {
    register_node(node_key, opened = false) {
      const node = ensureNode(store, node_key);
      if (!node) return;
      node.opened = Boolean(opened);
    },

    set_node_opened(node_key, opened = true) {
      const node = ensureNode(store, node_key);
      if (!node) return;
      node.opened = Boolean(opened);
    },

    register_card(card_key, parent_node_key) {
      const card = ensureCard(store, card_key);
      if (!card) return;
      linkCardToNode(store, card.card_key, parent_node_key);
    },

    mark_card_opened(card_key) {
      const card = ensureCard(store, card_key);
      if (!card) return;
      card.opened = true;
    },

    set_generated_children_count(card_key, count) {
      const card = ensureCard(store, card_key);
      if (!card) return;
      card.generated_children_count = toNonNegativeInt(count);
    },

    set_explored_children_count(card_key, count) {
      const card = ensureCard(store, card_key);
      if (!card) return;
      card.explored_children_count = toNonNegativeInt(count);
    },

    compute_card_exploration(card_state_or_key) {
      if (typeof card_state_or_key === "string") {
        const card = store.cards[card_state_or_key];
        return compute_card_exploration(card || {});
      }
      return compute_card_exploration(card_state_or_key || {});
    },

    compute_node_exploration(node_key) {
      return computeNodeExplorationFromStore(store, node_key);
    },

    compute_exploration_summary(node_key) {
      return computeNodeSummaryFromStore(store, node_key);
    },

    snapshot() {
      return {
        nodes: Object.values(store.nodes).map((node) => ({
          node_key: node.node_key,
          opened: Boolean(node.opened),
          cards: [...node.cards],
        })),
        cards: Object.values(store.cards).map((card) => ({
          ...card,
        })),
      };
    },
  };
}
