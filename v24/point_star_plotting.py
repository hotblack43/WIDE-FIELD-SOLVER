"""Shared plotting output helpers."""


def arrange_source_labels(axis):
    """Arrange source annotations after final sizing; never move their anchors.

    All adjustment uses display pixels, including obstacle boxes: passing data
    boxes through an inverted detector-y transform reverses their min/max edges.
    Convert only the resulting text positions back to data. Export at this DPI.
    """
    from adjustText import adjust_text
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import FancyArrowPatch
    from matplotlib.text import Annotation
    from matplotlib.transforms import Bbox, IdentityTransform
    import numpy as np

    figure = axis.figure
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    renderer = canvas.get_renderer()
    labels = [text for text in axis.texts if isinstance(text, Annotation) and text.get_text()]
    if not labels:
        return dict(engine='adjustText', label_count=0, remaining_conflicts=[])
    targets = np.asarray([text.xy for text in labels], dtype=float)
    target_display = axis.transData.transform(targets)
    for text in labels:
        position = text.get_transform().transform(text.get_position())
        text.anncoords = IdentityTransform()
        text.set_transform(IdentityTransform())
        text.set_position(position)
        text.arrow_patch = None
        text.arrowprops = None
    fixed = [line.get_window_extent(renderer).padded(2.) for line in axis.lines]
    legend = axis.get_legend()
    if legend is not None:
        fixed.append(legend.get_window_extent(renderer).padded(3.))
    fixed.extend((text.get_bbox_patch() or text).get_window_extent(renderer).padded(3.)
                 for text in axis.texts if text not in labels and text.get_text())
    edge = axis.bbox
    # Reserve an inset so the rounded label boxes, not just glyphs, stay inside.
    margin = renderer.points_to_pixels(5.)
    fixed.extend([Bbox.from_extents(edge.x0, edge.y0, edge.x0+margin, edge.y1),
                  Bbox.from_extents(edge.x1-margin, edge.y0, edge.x1, edge.y1),
                  Bbox.from_extents(edge.x0, edge.y0, edge.x1, edge.y0+margin),
                  Bbox.from_extents(edge.x0, edge.y1-margin, edge.x1, edge.y1)])
    adjust_text(labels, target_x=target_display[:, 0], target_y=target_display[:, 1],
                objects=fixed, ax=axis, expand=(1.18, 1.65),
                force_text=(.3, .5), force_static=(.5, .8), force_pull=(.005, .005),
                iter_lim=400, ensure_inside_axes=True, prevent_crossings=True)
    for text in labels:
        text.set_position(axis.transData.inverted().transform(text.get_position()))
        text.anncoords = 'data'
        text.set_transform(axis.transData)
    canvas.draw()
    boxes = [text.get_bbox_patch().get_window_extent(renderer) for text in labels]
    # The optimiser is heuristic: settle any remaining *rendered box* conflict
    # with the nearest clear local translation, retaining all text and anchors.
    for i, (text, box) in enumerate(zip(labels, boxes)):
        obstacles = fixed + [other.padded(1.) for j, other in enumerate(boxes) if j != i]
        inside = lambda b: edge.contains(b.x0, b.y0) and edge.contains(b.x1, b.y1)
        if inside(box) and not any(box.overlaps(other) for other in obstacles):
            continue
        position = axis.transData.transform(text.get_position())
        away = np.arctan2(*(position-target_display[i])[::-1])
        found = False
        for radius in renderer.points_to_pixels(np.arange(2., 162., 2.)):
            for angle in away+np.linspace(0., 2*np.pi, 24, endpoint=False):
                dx, dy = radius*np.cos(angle), radius*np.sin(angle)
                candidate = Bbox.from_bounds(box.x0+dx, box.y0+dy, box.width, box.height)
                if inside(candidate) and not any(candidate.overlaps(other) for other in obstacles):
                    text.set_position(axis.transData.inverted().transform(position+[dx, dy]))
                    boxes[i] = candidate
                    found = True
                    break
            if found:
                break
    canvas.draw()
    boxes = [text.get_bbox_patch().get_window_extent(renderer) for text in labels]
    conflicts = []
    for i, (text, box) in enumerate(zip(labels, boxes)):
        for j in range(i+1, len(labels)):
            if box.overlaps(boxes[j]):
                conflicts.append(dict(label=text.get_text(), other=labels[j].get_text()))
        if any(box.overlaps(obstacle) for obstacle in fixed):
            conflicts.append(dict(label=text.get_text(), other='fixed obstacle / image margin'))
        if not (edge.contains(box.x0, box.y0) and edge.contains(box.x1, box.y1)):
            conflicts.append(dict(label=text.get_text(), other='outside image'))
        axis.add_patch(FancyArrowPatch(text.get_position(), targets[i], transform=axis.transData,
                                      patchA=text.get_bbox_patch(), arrowstyle='-',
                                      shrinkA=2., shrinkB=9., color=text.get_color(),
                                      linewidth=.55, alpha=.8, zorder=2.5))
    if conflicts:
        import warnings
        warnings.warn(f'{len(conflicts)} unresolved sky-label conflicts; see report_label_layout.json',
                      RuntimeWarning, stacklevel=2)
    return dict(engine='adjustText', label_count=len(labels), remaining_conflicts=conflicts,
                dpi=figure.dpi, positions=[dict(label=text.get_text(), source_xy=target.tolist(),
                                               text_xy=list(text.get_position()))
                                          for text, target in zip(labels, targets)])


def save_png(figure, target, **kwargs):
    """Save a figure as a lossless PNG with fast compression."""
    figure.savefig(target, pil_kwargs={'compress_level': 1}, **kwargs)
