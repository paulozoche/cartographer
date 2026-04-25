import React from "https://esm.sh/react@18.3.1";
import { applyNavigationSeed, loadTree, persistTree, toggleExpanded } from "/static/components/explorationTreeState.js";
import { GrafoDetalhado } from "/static/components/GrafoDetalhado.js?v=graph-v1";

function OrientationNode({ node, tree, onToggle }) {
  const children = (node.children || [])
    .map((id) => tree.nodes[id])
    .filter(Boolean);

  const hasChildren = children.length > 0;
  const rowClass = `orientation-node-row ${node.current ? "is-current" : ""}`.trim();
  const labelClass = `orientation-node-link ${node.current ? "is-current" : ""} importance-${node.importance || "medium"}`;

  const dragPayload = JSON.stringify({
    label: node.label || node.id,
    state_reference: {
      href: node.href || "#",
      node_id: node.id,
      layer: node.kind || "origem",
    },
  });

  return React.createElement(
    "li",
    { className: "orientation-node", "data-state": node.current ? "current" : "idle" },
    React.createElement(
      "div",
      { className: rowClass },
      hasChildren
        ? React.createElement(
            "button",
            {
              type: "button",
              className: "orientation-toggle",
              onClick: () => onToggle(node.id),
              "aria-label": node.expanded ? "Recolher nó" : "Expandir nó",
              "aria-expanded": node.expanded,
            },
            node.expanded ? "▾" : "▸",
          )
        : React.createElement("span", { className: "orientation-toggle-placeholder" }, "·"),
      React.createElement(
        "a",
        {
          href: node.href || "#",
          className: labelClass,
          title: node.label,
          draggable: true,
          onDragStart: (event) => {
            event.dataTransfer.effectAllowed = "copy";
            event.dataTransfer.setData("application/x-agnostic-state-reference", dragPayload);
            event.dataTransfer.setData("text/plain", dragPayload);
          },
        },
        node.label,
      ),
    ),
    hasChildren && node.expanded
      ? React.createElement(
          "ul",
          { className: "orientation-children" },
          children.map((child) => React.createElement(OrientationNode, { key: child.id, node: child, tree, onToggle })),
        )
      : null,
  );
}

export function PainelOrientacao({ title, data, graph }) {
  const seed = data || {};
  const seedKey = JSON.stringify(seed);
  const hasGraph = Array.isArray(graph?.nodes) && graph.nodes.length > 0;
  const [showGraph, setShowGraph] = React.useState(false);

  const [tree, setTree] = React.useState(() => {
    const baseTree = loadTree(seed.sessionKey || "default");
    const nextTree = applyNavigationSeed(baseTree, seed);
    persistTree(seed.sessionKey || "default", nextTree);
    return nextTree;
  });

  React.useEffect(() => {
    const baseTree = loadTree(seed.sessionKey || "default");
    const nextTree = applyNavigationSeed(baseTree, seed);
    persistTree(seed.sessionKey || "default", nextTree);
    setTree(nextTree);
  }, [seed.sessionKey, seedKey]);

  const handleToggle = React.useCallback(
    (nodeId) => {
      setTree((previous) => {
        const next = toggleExpanded(previous, nodeId);
        persistTree(seed.sessionKey || "default", next);
        return { ...next };
      });
    },
    [seed.sessionKey],
  );

  const rootNode = tree.rootId ? tree.nodes[tree.rootId] : null;

  return React.createElement(
    "section",
    { className: "functional-panel orientation-panel", "aria-label": title },
    React.createElement("h2", null, title),
    hasGraph
      ? React.createElement(
          "div",
          { className: "orientation-panel-actions" },
          React.createElement(
            "button",
            {
              type: "button",
              className: "button secondary mini",
              onClick: () => setShowGraph((current) => !current),
              "aria-expanded": showGraph,
            },
            showGraph ? "Ocultar grafo detalhado" : "Ver grafo detalhado",
          ),
        )
      : null,
    React.createElement(
      "ul",
      { className: "orientation-tree-list", style: { marginTop: "8px" } },
      rootNode ? React.createElement(OrientationNode, { node: rootNode, tree, onToggle: handleToggle }) : null,
    ),
    showGraph ? React.createElement(GrafoDetalhado, { graph }) : null,
  );
}
