import React from "https://esm.sh/react@18.3.1";

const TYPE_LABELS = {
  source: "Origem",
  table: "Tabelas",
  column: "Colunas",
  decision: "Decisões",
  value: "Valores",
  row: "Linhas associadas",
  relation: "Relações",
  other: "Outros",
};

const TYPE_ORDER = ["source", "table", "column", "decision", "value", "row", "relation", "other"];

function safeNodes(graph) {
  return Array.isArray(graph?.nodes) ? graph.nodes.filter((node) => node && typeof node.id === "string") : [];
}

function safeEdges(graph) {
  return Array.isArray(graph?.edges) ? graph.edges.filter((edge) => edge && edge.from && edge.to) : [];
}

function GraphNodeLink({ node }) {
  const className = `graph-node-link ${node.current ? "is-current" : ""}`.trim();
  if (node.href) {
    return React.createElement("a", { href: node.href, className, title: node.label || node.id }, node.label || node.id);
  }
  return React.createElement("span", { className, title: node.label || node.id }, node.label || node.id);
}

export function GrafoDetalhado({ graph }) {
  const nodes = safeNodes(graph);
  const edges = safeEdges(graph);
  const nodesById = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const groupedNodes = TYPE_ORDER.map((type) => ({
    type,
    label: TYPE_LABELS[type],
    nodes: nodes.filter((node) => (node.type || "other") === type),
  })).filter((group) => group.nodes.length > 0);

  if (!nodes.length) {
    return React.createElement(
      "section",
      { className: "detailed-graph", "aria-label": "Grafo detalhado" },
      React.createElement("div", { className: "small" }, "Grafo indisponível para o estado atual."),
    );
  }

  return React.createElement(
    "section",
    { className: "detailed-graph", "aria-label": "Grafo detalhado" },
    React.createElement(
      "div",
      { className: "detailed-graph-groups" },
      groupedNodes.map((group) =>
        React.createElement(
          "div",
          { className: "detailed-graph-group", key: group.type },
          React.createElement("div", { className: "detailed-graph-group-title" }, group.label),
          React.createElement(
            "ul",
            { className: "detailed-graph-node-list" },
            group.nodes.map((node) =>
              React.createElement(
                "li",
                { className: `detailed-graph-node ${node.current ? "is-current" : ""}`.trim(), key: node.id },
                React.createElement(GraphNodeLink, { node }),
              ),
            ),
          ),
        ),
      ),
    ),
    React.createElement("div", { className: "detailed-graph-group-title" }, "Conexões"),
    React.createElement(
      "ul",
      { className: "detailed-graph-edge-list" },
      edges.length
        ? edges.map((edge, index) => {
            const fromNode = nodesById[edge.from] || { label: edge.from };
            const toNode = nodesById[edge.to] || { label: edge.to };
            return React.createElement(
              "li",
              { className: "detailed-graph-edge", key: `${edge.from}:${edge.to}:${index}` },
              React.createElement("span", null, fromNode.label || edge.from),
              React.createElement("span", { className: "detailed-graph-arrow" }, "→"),
              React.createElement("span", null, toNode.label || edge.to),
            );
          })
        : React.createElement("li", { className: "detailed-graph-edge" }, "Sem conexões adicionais."),
    ),
  );
}
