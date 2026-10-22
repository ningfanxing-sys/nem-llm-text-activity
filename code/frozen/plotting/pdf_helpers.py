'Inspect PDF text positions and hatch clipping for figure checks.'
from pathlib import Path

def audit_gap_hatches(path):

    import pymupdf as fitz
    import audit_figure_collisions as audit
    pages = audit.extract_pdf_geometry(Path(path))
    assert len(pages) == 1
    geometry = pages[0]
    document = fitz.open(path)
    page = document[0]
    plain = page.get_drawings()
    by_seq = {d['seqno']: i for i, d in enumerate(plain)}
    clips = {}
    changes = []
    tile_indexes = set()
    pattern_indexes = set()
    new_strokes = []
    new_fills = []
    for d in page.get_drawings(extended=True):
        level = d['level']
        clips = {k: v for k, v in clips.items() if k < level}
        if d['type'] == 'clip':
            clips[level] = tuple(d['scissor'])
            continue
        items = d['items']
        is_pattern = len(items) == 25 and d['type'] == 'fs' and (abs(d['width'] - 0.5) < 1e-06) and all((i[0] == 'l' and abs(i[2].x - i[1].x - 72) < 1e-06 and (abs(i[2].y - i[1].y + 72) < 1e-06) for i in items))
        if not is_pattern:
            continue
        assert clips, 'Unbounded hatch pattern'
        rect = clips[max(clips)]
        x0, y0, x1, y1 = rect
        assert y1 - y0 < 6 and x1 - x0 < 100, rect
        assert all((audit.rect_intersection(rect, t.bbox) is None for t in geometry.texts)), rect
        index = by_seq[d['seqno']]
        pattern_indexes.add(index)
        prior = plain[index - 1]
        assert prior['type'] == 'f' and len(prior['items']) == 1
        tile_indexes.add(index - 1)
        segments = []
        offset = x0 - (y1 - y0)
        while offset < x1:
            lo = max(x0, offset)
            hi = min(x1, offset + (y1 - y0))
            if hi > lo:
                segments.append(((lo, y1 - (lo - offset)), (hi, y1 - (hi - offset))))
            offset += 3
        new_strokes.append(audit.StrokePath(index=index, bbox=rect, width=0.5, segments=tuple(segments)))
        new_fills.append(audit.FilledRegion(index=index * 1000, bbox=rect, source='fill'))
        changes.append({'path_index': index, 'clip_bbox_pt': rect, 'role': 'legend Gap' if y0 < 20 else 'archive Gap'})
    assert len(changes) == 3 and sum((c['role'] == 'legend Gap' for c in changes)) == 1, changes
    geometry.strokes = [p for p in geometry.strokes if p.index not in pattern_indexes] + new_strokes
    geometry.fills = [p for p in geometry.fills if p.index not in pattern_indexes and p.index // 1000 not in tile_indexes] + new_fills
    result = {'pdf': str(path), **audit.audit_geometries(pages), 'gap_pattern_clip_correction': changes}
    document.close()
    return result
