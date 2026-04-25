from __future__ import annotations

from html import escape


def render_card_header(
    *,
    title: str,
    occurrences: int | None,
    exploration_level: float,
    can_add_to_collection: bool,
    can_share: bool,
    can_mark_seen: bool = False,
    can_star: bool = True,
) -> str:
    clamped = max(0.0, min(float(exploration_level), 1.0))
    occ_html = f"<span class='card-head-occurrences'>({int(occurrences)})</span>" if occurrences is not None else ""
    add_button = (
        """
        <span class="card-head-action" data-card-action="add-to-collection" role="img" aria-label="Adicionar à coleção" title="Adicionar à coleção">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        </span>
        """
        if can_add_to_collection
        else ""
    )
    share_button = (
        """
        <span class="card-head-action" data-card-action="share" role="img" aria-label="Compartilhar" title="Compartilhar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="18" cy="5" r="3"></circle>
            <circle cx="6" cy="12" r="3"></circle>
            <circle cx="18" cy="19" r="3"></circle>
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line>
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
          </svg>
        </span>
        """
        if can_share
        else ""
    )
    star_button = (
        """
        <span class="card-head-action" data-card-action="star" role="img" aria-label="Favoritar" title="Favoritar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
          </svg>
        </span>
        """
        if can_star
        else ""
    )
    seen_button = (
        """
        <span class="card-head-action" data-card-action="mark-seen" role="img" aria-label="Marcar como visto" title="Marcar como visto">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9"></circle>
            <polyline points="9 12 11 14 15 10"></polyline>
          </svg>
        </span>
        """
        if can_mark_seen
        else ""
    )
    actions_html = (
        f"<div class='card-head-actions'>{add_button}{share_button}{star_button}{seen_button}</div>"
        if (can_add_to_collection or can_share or can_star or can_mark_seen)
        else ""
    )
    return f"""
      <div class="card-head-row">
        <div class="card-head-left">
          <span class="card-head-progress" aria-hidden="true"><span class="card-head-progress-fill" style="width:{clamped * 100:.2f}%"></span></span>
          <span class="card-head-title">{escape(title)}</span>
          <span class="card-head-stars" hidden aria-label="sem estrelas"></span>
          {occ_html}
        </div>
        {actions_html}
      </div>
    """


def render_info_card(
    *,
    title: str,
    body_html: str,
    class_name: str = "",
    aria_label: str | None = None,
    can_add_to_collection: bool = False,
    can_share: bool = False,
    can_mark_seen: bool = False,
    can_star: bool = False,
) -> str:
    classes = "focus-stat-card h-card"
    if class_name:
        classes = f"{classes} {class_name}"
    aria = f' aria-label="{escape(aria_label)}"' if aria_label else ""
    return f"""
      <article class="{escape(classes)}"{aria}>
        {render_card_header(
            title=title,
            occurrences=None,
            exploration_level=0.0,
            can_add_to_collection=can_add_to_collection,
            can_share=can_share,
            can_mark_seen=can_mark_seen,
            can_star=can_star,
        )}
        {body_html}
      </article>
    """
