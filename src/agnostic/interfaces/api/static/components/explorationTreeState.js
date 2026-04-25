const STORAGE_PREFIX = "agnostic-exploration-tree:";
const NAVIGATION_STORAGE_PREFIX = "agnostic-navigation-state:";
const MAX_NODES = 280;

function nowIso() {
  return new Date().toISOString();
}

function emptyTree() {
  return {
    version: 1,
    rootId: null,
    currentId: null,
    nodes: {},
  };
}

function sanitizeTree(raw) {
  if (!raw || typeof raw !== "object") return emptyTree();
  const nodes = raw.nodes && typeof raw.nodes === "object" ? raw.nodes : {};
  return {
    version: 1,
    rootId: typeof raw.rootId === "string" ? raw.rootId : null,
    currentId: typeof raw.currentId === "string" ? raw.currentId : null,
    nodes,
  };
}

function storageKey(sessionKey) {
  return `${STORAGE_PREFIX}${sessionKey || "default"}`;
}

function navigationStorageKey(sessionKey) {
  return `${NAVIGATION_STORAGE_PREFIX}${sessionKey || "default"}`;
}

function emptyNavigationState() {
  return {
    path: [],
    focusIndex: -1,
  };
}

function toNavigationNode(node) {
  if (!node || typeof node.id !== "string") return null;
  return {
    id: node.id,
    label: typeof node.label === "string" ? node.label : node.id,
    href: typeof node.href === "string" ? node.href : "#",
    kind: typeof node.kind === "string" ? node.kind : "node",
    importance: typeof node.importance === "string" ? node.importance : "medium",
  };
}

function sanitizeNavigationState(raw) {
  if (!raw || typeof raw !== "object") return emptyNavigationState();
  const path = Array.isArray(raw.path)
    ? raw.path
        .map((node) => toNavigationNode(node))
        .filter(Boolean)
    : [];

  const focusIndexRaw = Number(raw.focusIndex);
  const boundedFocus = Number.isFinite(focusIndexRaw)
    ? Math.trunc(focusIndexRaw)
    : (path.length ? path.length - 1 : -1);

  return {
    path,
    focusIndex: Math.max(-1, Math.min(boundedFocus, path.length - 1)),
  };
}

function loadNavigationState(sessionKey) {
  try {
    const raw = sessionStorage.getItem(navigationStorageKey(sessionKey));
    if (!raw) return emptyNavigationState();
    return sanitizeNavigationState(JSON.parse(raw));
  } catch {
    return emptyNavigationState();
  }
}

function persistNavigationState(sessionKey, state) {
  try {
    sessionStorage.setItem(
      navigationStorageKey(sessionKey),
      JSON.stringify(sanitizeNavigationState(state)),
    );
  } catch {
    // no-op
  }
}

function resolveSeedNodeById(seed, nodeId) {
  if (!nodeId || typeof nodeId !== "string") return null;
  const seedPath = Array.isArray(seed?.path) ? seed.path : [];
  const seedNodes = Array.isArray(seed?.nodes) ? seed.nodes : [];
  const catalog = seedPath.concat(seedNodes);
  for (const node of catalog) {
    if (!node || typeof node.id !== "string") continue;
    if (node.id !== nodeId) continue;
    return toNavigationNode(node);
  }
  return null;
}

function reconcileNavigationState(previousState, seed) {
  const state = sanitizeNavigationState(previousState);
  const seedPath = Array.isArray(seed?.path) ? seed.path : [];
  const seedCurrentId = typeof seed?.currentNodeId === "string" ? seed.currentNodeId : null;
  const fallbackCurrentId = seedPath.length ? seedPath[seedPath.length - 1]?.id : null;
  const currentId = seedCurrentId || fallbackCurrentId;

  if (seedPath.length) {
    state.path = seedPath
      .map((node) => toNavigationNode(node))
      .filter(Boolean);
    const currentIndex = currentId
      ? state.path.findIndex((node) => node.id === currentId)
      : -1;
    state.focusIndex = currentIndex >= 0
      ? currentIndex
      : (state.path.length ? state.path.length - 1 : -1);
  } else if (currentId && typeof currentId === "string") {
    const currentNode = resolveSeedNodeById(seed, currentId) || {
      id: currentId,
      label: currentId,
      href: "#",
      kind: "node",
      importance: "medium",
    };
    state.path = [currentNode];
    state.focusIndex = 0;
  }

  if (!state.path.length) {
    state.focusIndex = -1;
  } else if (state.focusIndex < 0 || state.focusIndex >= state.path.length) {
    state.focusIndex = state.path.length - 1;
  }

  return state;
}

export function loadTree(sessionKey) {
  try {
    const raw = sessionStorage.getItem(storageKey(sessionKey));
    if (!raw) return emptyTree();
    return sanitizeTree(JSON.parse(raw));
  } catch {
    return emptyTree();
  }
}

export function persistTree(sessionKey, tree) {
  try {
    sessionStorage.setItem(storageKey(sessionKey), JSON.stringify(tree));
  } catch {
    // no-op
  }
}

function ensureNode(tree, node, parentId) {
  const existing = tree.nodes[node.id] || null;
  const previousParentId = existing?.parentId || null;
  const createdAt = existing?.createdAt || nowIso();
  const expanded = Boolean(existing?.expanded);

  tree.nodes[node.id] = {
    id: node.id,
    label: node.label,
    href: node.href,
    kind: node.kind,
    importance: node.importance || existing?.importance || "medium",
    parentId,
    children: Array.isArray(existing?.children) ? existing.children : [],
    visited: true,
    current: false,
    expanded,
    collapsed: !expanded,
    createdAt,
    updatedAt: nowIso(),
    lastVisitedAt: nowIso(),
  };

  if (previousParentId && previousParentId !== parentId) {
    const previousParent = tree.nodes[previousParentId];
    if (previousParent) {
      previousParent.children = previousParent.children.filter((child) => child !== node.id);
      previousParent.updatedAt = nowIso();
    }
  }

  if (parentId) {
    const parent = tree.nodes[parentId];
    if (parent && !parent.children.includes(node.id)) {
      parent.children.push(node.id);
      parent.updatedAt = nowIso();
    }
  }
}

function pruneTree(tree, keepIds) {
  const ids = Object.keys(tree.nodes);
  if (ids.length <= MAX_NODES) return;

  const removableLeaves = ids
    .filter((id) => !keepIds.has(id))
    .filter((id) => {
      const node = tree.nodes[id];
      return node && (!node.children || node.children.length === 0);
    })
    .sort((a, b) => {
      const ta = tree.nodes[a]?.lastVisitedAt || "";
      const tb = tree.nodes[b]?.lastVisitedAt || "";
      return ta.localeCompare(tb);
    });

  while (Object.keys(tree.nodes).length > MAX_NODES && removableLeaves.length > 0) {
    const id = removableLeaves.shift();
    if (!id) break;
    const node = tree.nodes[id];
    if (!node) continue;
    const parent = node.parentId ? tree.nodes[node.parentId] : null;
    if (parent) {
      parent.children = parent.children.filter((child) => child !== id);
      parent.updatedAt = nowIso();
    }
    delete tree.nodes[id];
  }
}

function removeDeprecatedDecisionGroupNodes(tree) {
  for (const id of Object.keys(tree.nodes)) {
    const node = tree.nodes[id];
    if (!node) continue;
    const isDeprecatedGroup =
      id.includes("::decisoes") ||
      node.label === "decisões de aprofundamento";
    if (!isDeprecatedGroup) continue;

    const parent = node.parentId ? tree.nodes[node.parentId] : null;
    if (parent) {
      parent.children = (parent.children || []).filter((child) => child !== id);
      parent.updatedAt = nowIso();
    }
    for (const childId of node.children || []) {
      const child = tree.nodes[childId];
      if (child && child.parentId === id) {
        child.parentId = node.parentId || null;
      }
      if (parent && !parent.children.includes(childId)) {
        parent.children.push(childId);
      }
    }
    delete tree.nodes[id];
  }
}

export function applyNavigationSeed(previousTree, seed) {
  const tree = sanitizeTree(previousTree);
  const sessionKey = seed?.sessionKey || "default";
  const navigationState = reconcileNavigationState(loadNavigationState(sessionKey), seed);
  const path = navigationState.path;
  const seedNodes = Array.isArray(seed?.nodes) ? seed.nodes : [];
  if (!path.length && !seedNodes.length) return tree;

  let parentId = null;
  const keepIds = new Set();
  for (const node of path) {
    if (!node || typeof node.id !== "string") continue;
    ensureNode(tree, node, parentId);
    parentId = node.id;
    keepIds.add(node.id);
  }

  for (const node of seedNodes) {
    if (!node || typeof node.id !== "string") continue;
    const explicitParentId = typeof node.parentId === "string" ? node.parentId : null;
    ensureNode(tree, node, explicitParentId);
    keepIds.add(node.id);
    if (explicitParentId) keepIds.add(explicitParentId);
  }

  removeDeprecatedDecisionGroupNodes(tree);

  const focusedNode = navigationState.focusIndex >= 0 ? navigationState.path[navigationState.focusIndex] : null;
  const currentId = (focusedNode && focusedNode.id) || seed?.currentNodeId || parentId;
  tree.currentId = currentId;
  tree.rootId = path[0]?.id || tree.rootId || (typeof seedNodes[0]?.id === "string" ? seedNodes[0].id : null);
  if (currentId) keepIds.add(currentId);

  const pathIds = new Set(path.map((node) => node.id));

  Object.values(tree.nodes).forEach((node) => {
    node.current = node.id === currentId;
    node.visited = true;

    if (pathIds.has(node.id)) {
      node.expanded = true;
      node.collapsed = false;
    } else {
      if (node.kind !== "origem") {
        node.expanded = false;
        node.collapsed = true;
      }
    }
  });

  pruneTree(tree, new Set([...pathIds, ...keepIds]));
  persistNavigationState(sessionKey, navigationState);
  return tree;
}

export function toggleExpanded(previousTree, nodeId) {
  const tree = sanitizeTree(previousTree);
  const node = tree.nodes[nodeId];
  if (!node) return tree;
  node.expanded = !node.expanded;
  node.collapsed = !node.expanded;
  node.updatedAt = nowIso();
  return tree;
}
