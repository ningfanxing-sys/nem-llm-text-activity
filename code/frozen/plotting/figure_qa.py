'Inspect PDF fonts, vector objects and colour-vision previews.'
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from PIL import Image

def run_qa(here, root, qa_dir, audit_scripts, qa, stems=None):
    palette = {'Fields': '#AA3377', 'Embeddings': '#946B00', 'Event states': '#0072B2', 'Overlap components': '#00845F', 'Archive embeddings': '#B34E00', 'Non-LLM': '#8C8C8C', 'Activity': '#222222'}
    matrix = np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]])
    contrast = {}
    for name, hex_colour in palette.items():
        rgb = np.array([int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)])
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        lum = float(linear @ np.array([0.2126, 0.7152, 0.0722]))
        ratio = 1.05 / (lum + 0.05)
        assert ratio >= 3, (name, ratio)
        if name not in ('Non-LLM', 'Activity'):
            assert ratio >= 4.5, (name, ratio)
        cvd = np.clip(linear @ matrix.T, 0, 1)
        contrast[name] = {'hex': hex_colour, 'white_contrast': ratio, 'deuteranopia_white_contrast': 1.05 / (float(cvd @ np.array([0.2126, 0.7152, 0.0722])) + 0.05)}
    qa['colour_checks'] = {'status': 'PASS', 'normal_mark_threshold': 3, 'coloured_text_threshold': 4.5, 'palette': contrast, 'simulation': 'Machado 2009, severity 100, linear sRGB; greyscale luminance', 'redundant_encoding': 'Direct labels, filled/open circles and activity diamonds in Figure 3 (no non-LLM squares); overlap dash in Fig. 4', 'guide_exception': 'Light-grey dumbbell connectors and background bands are auxiliary guides, with dark semantic marks over them.'}
    source = subprocess.run([sys.executable, '-B', str(audit_scripts / 'validate_figure.py'), str(here / 'make_figures.py'), '--json'], text=True, capture_output=True)
    report = json.loads(source.stdout)
    (qa_dir / 'source-preflight.json').write_text(source.stdout)
    overrides = {'export-VECTOR': 'PDF is the vector output format used for the paper.', 'export-RASTER': 'PNG previews use 300 dpi.'}
    failures = [f for f in report['findings'] if f['level'] == 'FAIL']
    assert all((f['check_id'] in overrides for f in failures)), failures
    qa['source_preflight'] = {'raw_report': report, 'format_overrides': {f['check_id']: overrides[f['check_id']] for f in failures}, 'resolved_status': 'PASS for PDF figures and PNG previews', 'warning_review': '300-dpi PNGs are previews; the submission PDFs are vector. Width is measured at 6.30 in. Daily context means are descriptive; all 26 Figure 3 estimates use the frozen seed-averaged seven-day intervals; one-day intervals remain in Table A1. No white text masks are used.'}
    audit_python = root.parents[3] / '.venv/bin/python'
    assert audit_python.is_file(), 'Local PyMuPDF environment unavailable'
    subset_tags = {}
    for stem in stems if stems is not None else ['figure_2_timeline', 'figure_3_primary_effects', 'figure_4_cumulative']:
        pdf = here / f'{stem}.pdf'
        glyph = subprocess.run([sys.executable, '-B', str(audit_scripts / 'audit_pdf_text.py'), str(pdf), '--min-pt', '7.5', '--json'], text=True, capture_output=True)
        assert glyph.returncode == 0, glyph.stdout + glyph.stderr
        g = json.loads(glyph.stdout)
        (qa_dir / f'{stem}.text-audit.json').write_text(glyph.stdout)
        assert g['auditable'] and g['below_minimum_count'] == 0
        out = qa_dir / f'{stem}.collision-audit.json'
        if stem == 'figure_2_timeline':
            code = 'import sys,json\nsys.path[:0]=[sys.argv[1],sys.argv[2]]\nfrom pdf_helpers import audit_gap_hatches\nprint(json.dumps(audit_gap_hatches(sys.argv[3])))\n'
            c = subprocess.run([str(audit_python), '-B', '-c', code, str(here), str(audit_scripts), str(pdf)], text=True, capture_output=True, check=True)
            r = json.loads(c.stdout)
            out.write_text(json.dumps(r, indent=2))
            qa[stem]['gap_pattern_clip_correction'] = r['gap_pattern_clip_correction']
        else:
            c = subprocess.run([str(audit_python), '-B', str(audit_scripts / 'audit_figure_collisions.py'), str(pdf), '--json-out', str(out)], text=True, capture_output=True)
            assert c.returncode in [0, 1], c.stdout + c.stderr
            r = json.loads(out.read_text())
        qa[stem].update(pdf_text_minimum_pt=g['minimum_found_pt'], pdf_collision=r['verdict'], pdf_collision_counts=r['summary'])
        print(stem, g['minimum_found_pt'], r['verdict'], r['summary'])
        for finding in r['findings']:
            if finding['severity'] in ['FAIL', 'WARN']:
                print(finding)
        code = "import pymupdf as fitz,json,sys,hashlib\np=fitz.open(sys.argv[1])[0]\nfonts=p.get_fonts(full=True)\nembedded=[]\nfor f in fonts:\n    name,ext,kind,data=p.parent.extract_font(f[0])\n    embedded.append({'name':f[3],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})\nprint(json.dumps({'width_in':p.rect.width/72,'height_in':p.rect.height/72,'fonts':fonts,'embedded_fonts':embedded,'raster_images':len(p.get_images(full=True)),'text_characters':len(p.get_text()),'extracted_text':p.get_text()}))\n"
        result = subprocess.run([str(audit_python), '-c', code, str(pdf)], capture_output=True, text=True, check=True)
        vector = json.loads(result.stdout)
        qa[stem]['pdf_structure'] = vector
        vector.pop('extracted_text')
        assert abs(vector['width_in'] - 6.3) < 1e-05 and vector['raster_images'] == 0
        assert all((f[1] == 'ttf' and f[2] == 'Type0' for f in vector['fonts'])), vector
        for font in vector['embedded_fonts']:
            assert font['bytes'] > 0, font
            tag = font['name'].split('+')[0]
            assert len(tag) == 6 and tag.isupper(), font
            assert tag not in subset_tags, (tag, stem, subset_tags.get(tag))
            subset_tags[tag] = {'figure': stem, **font}
        with Image.open(here / f'{stem}.png') as im:
            rgba = np.array(im)
            rgb = rgba[:, :, :3] / 255
            assert rgba.shape[1] == 1890
            if rgba.shape[2] == 4:
                assert (rgba[:, :, 3] == 255).all()
            matrix = np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]])
            linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
            sim = np.clip(linear @ matrix.T, 0, 1)
            sim = np.where(sim <= 0.0031308, sim * 12.92, 1.055 * sim ** (1 / 2.4) - 0.055)
            grey = linear @ np.array([0.2126, 0.7152, 0.0722])
            grey = np.where(grey <= 0.0031308, grey * 12.92, 1.055 * grey ** (1 / 2.4) - 0.055)
            Image.fromarray(np.uint8(np.round(sim * 255))).save(qa_dir / f'{stem}.deuteranopia.png')
            Image.fromarray(np.uint8(np.round(grey * 255))).save(qa_dir / f'{stem}.greyscale.png')
            qa[stem]['png'] = {'width_px': im.width, 'height_px': im.height, 'dpi': list(im.info.get('dpi', ())), 'opaque': True}
    qa['subset_tags'] = {'status': 'PASS', 'unique_tag_count': len(subset_tags), 'tags': subset_tags}
    (qa_dir / 'qa-summary.json').write_text(json.dumps(qa, indent=2))
    return all((q.get('pdf_collision_counts', {}).get('fail', 0) == 0 and q.get('pdf_collision_counts', {}).get('warn', 0) == 0 for q in qa.values() if isinstance(q, dict)))
