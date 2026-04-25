import React from "https://esm.sh/react@18.3.1";

export function PainelFerramentas({ title, subtitle, html }) {
  const [collapsed, setCollapsed] = React.useState(true);

  return React.createElement(
    "section",
    { className: "functional-panel tools-panel", "aria-label": title, "data-collapsed": collapsed ? "1" : "0" },
    React.createElement(
      "div",
      { className: "panel-header-row" },
      React.createElement("h2", null, title),
      React.createElement(
        "button",
        {
          type: "button",
          className: "button secondary mini",
          onClick: () => setCollapsed((value) => !value),
          "aria-expanded": !collapsed,
          style: { minWidth: "auto", flex: "0 0 auto" },
        },
        collapsed ? "Expandir" : "Recolher",
      ),
    ),
    React.createElement("div", { className: "small" }, subtitle),
    !collapsed
      ? React.createElement("div", {
          style: { marginTop: "8px" },
          dangerouslySetInnerHTML: { __html: html || "" },
        })
      : React.createElement("div", { className: "small", style: { marginTop: "8px" } }, "Painel recolhido."),
  );
}
