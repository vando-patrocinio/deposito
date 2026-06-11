"""Renderiza as 5 silhuetas do veículo (frente / traseira / lateral esq /
lateral dir / vista superior) no PDF do checklist veicular usando primitives
ReportLab. Coordenadas alinhadas ao SVG do frontend (viewBox 0..200 × 0..110).

Cada silhueta ocupa um Drawing de 200 × 110 px (escala automática do reportlab.platypus).
Marks de avaria são círculos vermelhos numerados (mesmo `ord` do frontend).
"""
from __future__ import annotations


NERVOUS_METADATA = {
    "owner": "ops-team",
    "domain": "operacoes",
    "criticality": "high",
    "emits_events": False,
    "event_types": [],
    "company_id_required": True,
}

from reportlab.graphics.shapes import (Circle, Drawing, Ellipse, Line, Path,
                                        Polygon, Rect, String, definePath)
from reportlab.lib import colors

# Paleta alinhada ao frontend
SLATE = colors.HexColor("#0b1220")
FILL = colors.HexColor("#f1f5f9")
GLASS = colors.HexColor("#dbeafe")
HEADLIGHT = colors.HexColor("#fde68a")
TAILLIGHT = colors.HexColor("#dc2626")
GRILL = colors.HexColor("#0b1220")
TIRE = colors.HexColor("#0b1220")

DAMAGE_COLORS = {
    "D": colors.HexColor("#dc2626"),  # amassado
    "S": colors.HexColor("#d97706"),  # risco
    "R": colors.HexColor("#7c2d12"),  # oxidação
    "F": colors.HexColor("#b91c1c"),  # quebrado
    "V": colors.HexColor("#0369a1"),  # vidro
    "P": colors.HexColor("#475569"),  # pintura
}

VIEW_LABELS = {
    "front":  "Frente",
    "rear":   "Traseira",
    "left":   "Lateral esquerda",
    "right":  "Lateral direita",
    "top":    "Vista superior",
}

# Coords do viewBox SVG: y cresce para baixo (web). ReportLab cresce para
# cima. Precisamos espelhar y → y_rl = 110 - y_svg em desenhos.


def _flip_y(y: float, h: float = 110.0) -> float:
    return h - y


def _path_filled(d: Drawing, points: list, fill, stroke=SLATE, sw=1.2):
    """Polígono fechado com lista [(x,y), ...] em coord SVG (y cresce p/ baixo)."""
    pts = []
    for x, y in points:
        pts.extend([x, _flip_y(y)])
    d.add(Polygon(points=pts, fillColor=fill, strokeColor=stroke, strokeWidth=sw))


def _line(d: Drawing, x1, y1, x2, y2, stroke=SLATE, sw=1.0, dash=None):
    ln = Line(x1, _flip_y(y1), x2, _flip_y(y2), strokeColor=stroke, strokeWidth=sw)
    if dash:
        ln.strokeDashArray = list(dash) if isinstance(dash, (tuple, list)) else [2, 2]
    d.add(ln)


def _rect(d: Drawing, x, y, w, h, fill, stroke=SLATE, sw=1.0):
    """Retângulo em coord SVG (y cresce p/ baixo). y é o topo."""
    d.add(Rect(x, _flip_y(y + h), w, h, fillColor=fill, strokeColor=stroke, strokeWidth=sw))


def _circle(d: Drawing, cx, cy, r, fill, stroke=SLATE, sw=1.0):
    d.add(Circle(cx, _flip_y(cy), r, fillColor=fill, strokeColor=stroke, strokeWidth=sw))


def _ellipse(d: Drawing, cx, cy, rx, ry, fill, stroke=SLATE, sw=1.0):
    d.add(Ellipse(cx, _flip_y(cy), rx, ry, fillColor=fill, strokeColor=stroke, strokeWidth=sw))


def _text(d: Drawing, x, y, txt, color=colors.white, size=7, bold=True):
    s = String(x, _flip_y(y) - size / 3, txt, fillColor=color, fontSize=size, textAnchor="middle")
    if bold:
        s.fontName = "Helvetica-Bold"
    d.add(s)


# ---------------------------------------------------------------------------
# Vistas
# ---------------------------------------------------------------------------
def _draw_side(d: Drawing, flip: bool = False):
    # Quando flip=True (lado direito), espelha em x.
    def fx(x: float) -> float:
        return 200 - x if flip else x

    # Corpo
    body = [(fx(10), 70), (fx(30), 50), (fx(65), 38), (fx(130), 38),
            (fx(165), 52), (fx(190), 60), (fx(190), 80), (fx(10), 80)]
    _path_filled(d, body, FILL, SLATE, 1.2)
    # Coluna entre janelas
    _line(d, fx(98), 38, fx(98), 60, SLATE, 0.8)
    # Janela dianteira
    _path_filled(d, [(fx(38), 52), (fx(65), 42), (fx(95), 42), (fx(95), 52)], GLASS, SLATE, 0.8)
    # Janela traseira
    _path_filled(d, [(fx(102), 42), (fx(130), 42), (fx(162), 52), (fx(102), 52)], GLASS, SLATE, 0.8)
    # Maçanetas
    _line(d, fx(55), 62, fx(65), 62, SLATE, 1.0)
    _line(d, fx(115), 62, fx(125), 62, SLATE, 1.0)
    # Rodas
    _circle(d, fx(50), 80, 11, TIRE, SLATE, 0.8)
    _circle(d, fx(50), 80, 6, colors.HexColor("#94a3b8"), SLATE, 0.4)
    _circle(d, fx(155), 80, 11, TIRE, SLATE, 0.8)
    _circle(d, fx(155), 80, 6, colors.HexColor("#94a3b8"), SLATE, 0.4)
    # Faróis
    _ellipse(d, fx(14), 68, 4, 2.5, HEADLIGHT, SLATE, 0.5)
    _ellipse(d, fx(186), 68, 3, 2, colors.HexColor("#fecaca"), SLATE, 0.5)


def _draw_front(d: Drawing):
    # Corpo (cantos arredondados aproximados via polígono)
    body = [(30, 90), (30, 50), (45, 32), (60, 28), (140, 28), (155, 32),
            (170, 50), (170, 90)]
    _path_filled(d, body, FILL, SLATE, 1.2)
    # Parabrisa
    _path_filled(d, [(50, 50), (60, 32), (140, 32), (150, 50)], GLASS, SLATE, 0.8)
    # Grade
    _rect(d, 68, 62, 64, 14, GRILL, SLATE, 0.6)
    _line(d, 72, 66, 128, 66, colors.HexColor("#475569"), 0.6)
    _line(d, 72, 70, 128, 70, colors.HexColor("#475569"), 0.6)
    # Faróis
    _rect(d, 34, 55, 22, 10, HEADLIGHT, SLATE, 0.6)
    _rect(d, 144, 55, 22, 10, HEADLIGHT, SLATE, 0.6)
    # Placa
    _rect(d, 84, 80, 32, 8, colors.white, SLATE, 0.5)
    # Retrovisores
    _rect(d, 22, 48, 8, 6, FILL, SLATE, 0.6)
    _rect(d, 170, 48, 8, 6, FILL, SLATE, 0.6)
    # Sombra das rodas
    _ellipse(d, 44, 92, 14, 3, TIRE, SLATE, 0.4)
    _ellipse(d, 156, 92, 14, 3, TIRE, SLATE, 0.4)


def _draw_rear(d: Drawing):
    body = [(30, 90), (30, 50), (45, 34), (60, 30), (140, 30), (155, 34),
            (170, 50), (170, 90)]
    _path_filled(d, body, FILL, SLATE, 1.2)
    # Vidro traseiro
    _rect(d, 50, 38, 100, 20, GLASS, SLATE, 0.8)
    # Lanternas
    _rect(d, 34, 62, 26, 12, TAILLIGHT, SLATE, 0.6)
    _rect(d, 140, 62, 26, 12, TAILLIGHT, SLATE, 0.6)
    _line(d, 35, 68, 59, 68, colors.HexColor("#fef2f2"), 0.5)
    _line(d, 141, 68, 165, 68, colors.HexColor("#fef2f2"), 0.5)
    # Placa
    _rect(d, 74, 78, 52, 10, colors.white, SLATE, 0.5)
    # Maçaneta porta-malas
    _rect(d, 92, 68, 16, 3, colors.HexColor("#94a3b8"), SLATE, 0.4)
    # Sombra rodas
    _ellipse(d, 44, 92, 14, 3, TIRE, SLATE, 0.4)
    _ellipse(d, 156, 92, 14, 3, TIRE, SLATE, 0.4)


def _draw_top(d: Drawing):
    # Corpo (aproximação de retângulo arredondado via polígono)
    body = [(40, 32), (60, 14), (140, 14), (160, 32),
            (160, 78), (140, 96), (60, 96), (40, 78)]
    _path_filled(d, body, FILL, SLATE, 1.2)
    # Parabrisa dianteiro
    _path_filled(d, [(56, 30), (144, 30), (138, 44), (62, 44)], GLASS, SLATE, 0.8)
    # Teto
    _rect(d, 62, 44, 76, 26, colors.HexColor("#e2e8f0"), SLATE, 0.5)
    # Parabrisa traseiro
    _path_filled(d, [(62, 70), (138, 70), (144, 84), (56, 84)], GLASS, SLATE, 0.8)
    # Divisão de portas
    _line(d, 100, 44, 100, 70, SLATE, 0.5, [2, 2])
    # Retrovisores
    _rect(d, 34, 40, 6, 10, FILL, SLATE, 0.6)
    _rect(d, 160, 40, 6, 10, FILL, SLATE, 0.6)


_VIEW_DRAWERS = {
    "front": _draw_front,
    "rear": _draw_rear,
    "top": _draw_top,
}


def silhouette_drawing(view: str, marks: list, width: float, height: float) -> Drawing:
    """Cria um Drawing pronto pra inserir no Story do platypus.

    width/height em pontos (1cm = 28.346 pt). O viewBox interno (200×110) é
    escalado proporcionalmente.
    """
    # Drawing usa coords de impressão (y cresce para cima), mas nossos
    # _flip_y já convertem do SVG.
    d = Drawing(200, 110)
    if view == "left":
        _draw_side(d, flip=False)
    elif view == "right":
        _draw_side(d, flip=True)
    else:
        drawer = _VIEW_DRAWERS.get(view)
        if drawer:
            drawer(d)
    # Marks
    for m in marks:
        if m.get("view") != view:
            continue
        color = DAMAGE_COLORS.get(m.get("code", "D"), DAMAGE_COLORS["D"])
        cx, cy = float(m.get("x", 0)), float(m.get("y", 0))
        _circle(d, cx, cy, 6, color, colors.white, 1.5)
        _text(d, cx, cy, str(m.get("ord", "?")), color=colors.white, size=7)
    # Escala final
    d.width = width
    d.height = height
    d.scale(width / 200.0, height / 110.0)
    return d
