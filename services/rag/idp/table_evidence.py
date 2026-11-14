"""Check literal row/column associations in exported HTML table chunks.

This is partial evidence coverage, not table precision, TEDS or answer accuracy.
No canonical cells or prose can substitute for missing table export structure.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from .structure import parse_table_html

TABLE_EVIDENCE_VERSION = "idp-table-evidence-1"


def _text(value):
    return ' '.join(unicodedata.normalize('NFC',value or '').split())


def _labels(values):
    if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() or len(v)>256 for v in values):
        raise ValueError('declare nonempty bounded table anchors before evaluation')
    return {_text(v) for v in values}


def table_fact_evidence(chunks,*,row_labels,value,column_labels=None,eligible_only=False):
    rows=_labels(row_labels);columns=_labels(column_labels) if column_labels is not None else None
    if not isinstance(value,str) or not value.strip() or len(value)>256:
        raise ValueError('invalid table fact value')
    pattern=re.compile(r'(?<!\w)'+re.escape(_text(value))+r'(?!\w|\.\d)')
    matches=[];tables=0
    for chunk in chunks:
        if chunk.get('content_kind')!='table' or (eligible_only and not chunk.get('publishable')):
            continue
        text=chunk['text']
        if len(text)>32768:
            raise ValueError('table evidence byte/character bound')
        for span in chunk.get('source_spans',[]):
            a,b=span.get('start'),span.get('end')
            if type(a) is not int or type(b) is not int or not 0<=a<=b<=len(text) or hashlib.sha256(text[a:b].encode('utf-8')).hexdigest()!=span.get('text_sha256'):
                raise ValueError('stale table source span')
        try:
            table=parse_table_html(text)
        except ValueError:
            continue
        if not table['rectangular']:
            continue
        tables+=1;cells=table['cells']
        anchors=[c for c in cells if _text(c.get('text')) in rows]
        headers=[c for c in cells if columns and _text(c.get('text')) in columns]
        for cell in cells:
            if not pattern.search(_text(cell.get('text'))):
                continue
            # A label encoded in one cell must describe this value's row span;
            # a value found elsewhere on the page cannot satisfy the relation.
            row_match=[r for r in anchors if r['column']+r.get('colspan',1)<=cell['column']
                       and r['row']<=cell['row'] and cell['row']+cell.get('rowspan',1)<=r['row']+r.get('rowspan',1)]
            column_match=[c for c in headers if c['row']+c.get('rowspan',1)<=cell['row']
                          and c['column']<=cell['column'] and cell['column']+cell.get('colspan',1)<=c['column']+c.get('colspan',1)]
            if row_match and (columns is None or column_match):
                matches.append({'chunk_id':chunk['id'],'table_id':chunk.get('table_id'),
                    'row':cell['row'],'column':cell['column'],'row_label':row_match[0]['text'],
                    'column_label':column_match[0]['text'] if column_match else None})
    return {'found':bool(matches),'matches':matches,'examined_table_chunks':tables,
            'scope':'declared_literal_row_column_evidence_not_precision_or_semantic_correctness'}
