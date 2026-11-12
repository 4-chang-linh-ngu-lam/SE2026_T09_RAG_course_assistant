"""MathType (Equation.DSMT4, MTEF v5) -> LaTeX.

Đọc stream "Equation Native" trong OLE object của MathType và dựng lại công thức LaTeX.
Tham chiếu định dạng: MathType MTEF v5 specification (Design Science).
"""
import struct

import olefile

# ---------------------------------------------------------------- bảng ký tự
CHARMAP = {
    0x00B1: r'\pm', 0x00D7: r'\times', 0x00F7: r'\div', 0x00B7: r'\cdot', 0x22C5: r'\cdot',
    0x2264: r'\le', 0x2265: r'\ge', 0x2260: r'\ne', 0x2248: r'\approx', 0x2261: r'\equiv',
    0x2192: r'\to', 0x2190: r'\leftarrow', 0x2194: r'\leftrightarrow', 0x21D2: r'\Rightarrow',
    0x21D0: r'\Leftarrow', 0x21D4: r'\Leftrightarrow', 0x2208: r'\in', 0x2209: r'\notin',
    0x220B: r'\ni', 0x2282: r'\subset', 0x2283: r'\supset', 0x2286: r'\subseteq', 0x2287: r'\supseteq',
    0x2284: r'\not\subset', 0x222A: r'\cup', 0x2229: r'\cap', 0x2205: r'\varnothing', 0x00D8: r'\varnothing',
    0x221E: r'\infty', 0x00B0: r'^{\circ}', 0x2218: r'\circ', 0x2200: r'\forall', 0x2203: r'\exists',
    0x2220: r'\angle', 0x2221: r'\measuredangle', 0x25B3: r'\triangle', 0x2206: r'\Delta', 0x22A5: r'\perp',
    0x2225: r'\parallel', 0x2226: r'\nparallel', 0x2032: "'", 0x2033: "''", 0x2026: r'\ldots',
    0x22EF: r'\cdots', 0x22EE: r'\vdots', 0x22F1: r'\ddots', 0x2211: r'\sum', 0x220F: r'\prod',
    0x222B: r'\int', 0x222C: r'\iint', 0x222D: r'\iiint', 0x222E: r'\oint', 0x221A: r'\sqrt{}',
    0x2202: r'\partial', 0x2207: r'\nabla', 0x2212: '-', 0x2013: '-', 0x2014: '-', 0x2215: '/',
    0x2223: r'\mid', 0x2016: r'\|', 0x2245: r'\cong', 0x223D: r'\backsim', 0x223C: r'\sim', 0x221D: r'\propto',
    0x2234: r'\therefore', 0x2235: r'\because', 0x2227: r'\wedge', 0x2228: r'\vee', 0x00AC: r'\neg',
    0x2102: r'\mathbb{C}', 0x2115: r'\mathbb{N}', 0x211A: r'\mathbb{Q}', 0x211D: r'\mathbb{R}',
    0x2124: r'\mathbb{Z}', 0x2329: r'\langle', 0x232A: r'\rangle', 0x27E8: r'\langle', 0x27E9: r'\rangle',
    0x230A: r'\lfloor', 0x230B: r'\rfloor', 0x2308: r'\lceil', 0x2309: r'\rceil',
    0x2191: r'\uparrow', 0x2193: r'\downarrow', 0x21C4: r'\rightleftarrows', 0x2213: r'\mp',
    0x226A: r'\ll', 0x226B: r'\gg', 0x2243: r'\simeq', 0x2259: r'\widehat{=}', 0x2266: r'\leqq', 0x2267: r'\geqq',
    0x2A7D: r'\leqslant', 0x2A7E: r'\geqslant', 0x2022: r'\bullet', 0x25CB: r'\circ', 0x2299: r'\odot',
    0x2295: r'\oplus', 0x2297: r'\otimes', 0x2032: "'", 0x0025: r'\%', 0x0023: r'\#', 0x0026: r'\&',
    0x007B: r'\{', 0x007D: r'\}', 0x005F: r'\_', 0x0024: r'\$', 0x005C: r'\backslash',
    0x0E000 + 0x3C: '<', 0x0E000 + 0x3E: '>', 0x2208: r'\in',
}
GREEK = 'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho varsigma sigma tau upsilon phi chi psi omega'.split()
for i, name in enumerate(GREEK):
    CHARMAP[0x03B1 + i] = '\\' + name
CHARMAP[0x03BF] = 'o'
CHARMAP.update({0x03D5: r'\phi', 0x03C6: r'\varphi', 0x03D1: r'\vartheta', 0x03F5: r'\epsilon', 0x03B5: r'\varepsilon'})
UGREEK = {0x0393: 'Gamma', 0x0394: 'Delta', 0x0398: 'Theta', 0x039B: 'Lambda', 0x039E: 'Xi', 0x03A0: 'Pi',
          0x03A3: 'Sigma', 0x03A5: 'Upsilon', 0x03A6: 'Phi', 0x03A8: 'Psi', 0x03A9: 'Omega'}
for k, v in UGREEK.items():
    CHARMAP[k] = '\\' + v
for k, v in zip(range(0x0391, 0x03AA), 'ABΓΔEZHΘIKΛMNΞOΠP ΣTΥΦXΨΩ'):
    if k not in CHARMAP and v.isascii() and v != ' ':
        CHARMAP[k] = v

FUNCS = {'sin', 'cos', 'tan', 'cot', 'log', 'ln', 'lg', 'exp', 'lim', 'max', 'min', 'sup', 'inf',
         'arcsin', 'arccos', 'arctan', 'sinh', 'cosh', 'tanh', 'det', 'deg', 'gcd', 'mod'}

# typeface (MTEF): 1 TEXT, 2 FUNCTION, 3 VARIABLE, 4 LCGREEK, 5 UCGREEK, 6 SYMBOL, 7 VECTOR, 8 NUMBER, 12 TEXT_FE, 24 SPACE
FN_TEXT, FN_FUNCTION, FN_VECTOR, FN_TEXT_FE, FN_SPACE = 1, 2, 7, 12, 24

EMBELL = {2: r'\dot', 3: r'\ddot', 4: r'\dddot', 8: r'\tilde', 9: r'\hat', 11: r'\overrightarrow',
          12: r'\overleftarrow', 13: r'\overleftrightarrow', 17: r'\overline', 22: r'\overrightarrow',
          19: r'\overset{\frown}', 24: r'\underline'}
PRIMES = {5: "'", 6: "''", 18: "'''"}

FENCES = {  # selector: (trái, phải)
    0: (r'\langle', r'\rangle'), 1: ('(', ')'), 2: (r'\{', r'\}'), 3: ('[', ']'), 4: ('|', '|'),
    5: (r'\|', r'\|'), 6: (r'\lfloor', r'\rfloor'), 7: (r'\lceil', r'\rceil'), 8: (r'[\![', r']\!]'),
}
BIGOPS = {16: r'\sum', 17: r'\prod', 18: r'\coprod', 19: r'\bigcup', 20: r'\bigcap', 22: r'\sum'}

OPT_NUDGE = 0x08


class MTEFError(Exception):
    pass


class Node:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)


class Reader:
    def __init__(self, data):
        self.d, self.i = data, 0

    def u8(self):
        if self.i >= len(self.d):
            raise MTEFError('hết dữ liệu')
        v = self.d[self.i]
        self.i += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.i)[0]
        self.i += 2
        return v

    def cstr(self):
        j = self.d.index(b'\0', self.i)
        s = self.d[self.i:j]
        self.i = j + 1
        return s

    def nudge(self):
        dx, dy = self.u8(), self.u8()
        if dx == 128 and dy == 128:  # dạng 16-bit
            self.i += 4

    def nibbles(self, n):
        """Bỏ qua n giá trị kích thước mã hoá theo nibble (kết thúc bằng 0xF)."""
        seen = 0
        while seen < n:
            b = self.u8()
            for nib in (b >> 4, b & 0xF):
                if nib == 0xF:
                    seen += 1
                    if seen == n:
                        break


def parse_header(r):
    ver = r.u8()
    if ver != 5:
        raise MTEFError(f'MTEF v{ver} chưa hỗ trợ')
    r.u8(); r.u8(); r.u8(); r.u8()  # platform, product, version, subversion
    r.cstr()  # application key
    r.u8()  # equation options


def parse_list(r):
    """Đọc danh sách record tới END; trả về list Node (bỏ các record định dạng)."""
    out = []
    while True:
        tag = r.u8()
        if tag == 0:
            return out
        node = parse_record(r, tag)
        if node is not None:
            out.append(node)


def parse_record(r, tag):
    if tag == 1:  # LINE
        opt = r.u8()
        if opt & OPT_NUDGE: r.nudge()
        if opt & 0x04: r.u16()  # line spacing
        if opt & 0x02: parse_ruler(r)
        items = [] if opt & 0x01 else parse_list(r)
        return Node('line', items=items)
    if tag == 2:  # CHAR
        opt = r.u8()
        if opt & OPT_NUDGE: r.nudge()
        tf = r.u8() - 128
        code = None
        if not opt & 0x20: code = r.u16()
        if opt & 0x04:
            c8 = r.u8()
            if code is None: code = c8
        if opt & 0x10:
            c16 = r.u16()
            if code is None: code = c16
        emb = parse_list(r) if opt & 0x01 else []
        return Node('char', tf=tf, code=code, emb=[e.etype for e in emb if e.kind == 'embell'],
                    func_start=bool(opt & 0x02))
    if tag == 3:  # TMPL
        opt = r.u8()
        if opt & OPT_NUDGE: r.nudge()
        sel = r.u8()
        var = r.u8()
        if var & 0x80:
            var = (var & 0x7F) | (r.u8() << 7)
        r.u8()  # template-specific options
        return Node('tmpl', sel=sel, var=var, subs=parse_list(r))
    if tag == 4:  # PILE
        opt = r.u8()
        if opt & OPT_NUDGE: r.nudge()
        halign, _ = r.u8(), r.u8()
        if opt & 0x02: parse_ruler(r)
        return Node('pile', halign=halign, lines=parse_list(r))
    if tag == 5:  # MATRIX
        opt = r.u8()
        if opt & OPT_NUDGE: r.nudge()
        r.u8(); r.u8(); r.u8()  # valign, h_just, v_just
        rows, cols = r.u8(), r.u8()
        r.i += ((rows + 1) * 2 + 7) // 8 + ((cols + 1) * 2 + 7) // 8
        return Node('matrix', rows=rows, cols=cols, cells=parse_list(r))
    if tag == 6:  # EMBELL
        opt = r.u8()
        if opt & OPT_NUDGE: r.nudge()
        return Node('embell', etype=r.u8())
    if tag == 7:
        parse_ruler(r, tagged=False); return None
    if tag == 8:  # FONT_STYLE_DEF
        r.u8(); r.u8(); return None
    if tag == 9:  # SIZE
        lsize = r.u8()
        if lsize == 101: r.u16()
        elif lsize == 100: r.u8(); r.u16()
        else: r.u8()
        return None
    if 10 <= tag <= 14:  # FULL, SUB, SUB2, SYM, SUBSYM
        return None
    if tag == 15:  # COLOR
        r.u8(); return None
    if tag == 16:  # COLOR_DEF
        opt = r.u8()
        r.i += 8 if opt & 0x01 else 6
        if opt & 0x04: r.cstr()
        return None
    if tag == 17:  # FONT_DEF
        r.u8(); r.cstr(); return None
    if tag == 18:  # EQN_PREFS
        r.u8()
        r.nibbles(r.u8())  # sizes
        r.nibbles(r.u8())  # spaces
        for _ in range(r.u8()):  # styles
            if r.u8(): r.u8()
        return None
    if tag == 19:  # ENCODING_DEF
        r.cstr(); return None
    if tag >= 100:  # FUTURE (MathType 7: độ dài 1 byte, 0xFF -> độ dài 16-bit)
        n = r.u8()
        if n == 0xFF: n = r.u16()
        blob = r.d[r.i:r.i + n]; r.i += n
        if blob.startswith(b'TeX Input Language\0'):
            return Node('annot', tex=blob.split(b'\0')[1].decode('latin1'))
        return None
    raise MTEFError(f'tag lạ {tag} tại {r.i}')


def parse_ruler(r, tagged=True):
    for _ in range(r.u8()):
        r.u8(); r.u16()


# ---------------------------------------------------------------- sinh LaTeX
def char_latex(n):
    c = n.code
    if c is None:
        return ''
    if n.tf == FN_SPACE or 0xEF00 <= c <= 0xEFFF or c in (0xEB00, 0xEB01, 0xEB02, 0xEB04, 0xEB05):
        return ' ' if c in (0xEF04, 0xEF05, 0xEB05) else ''
    if 0xE000 <= c <= 0xF8FF:
        return CHARMAP.get(c, '')  # private-use (MT Extra) không biết -> bỏ
    s = CHARMAP.get(c)
    if s is None:
        s = chr(c)
    return s


def wrap_embell(s, emb):
    for e in emb:
        if e in PRIMES:
            s += PRIMES[e]
        elif e == 10:
            s = r'\not' + s
        elif e in EMBELL:
            s = EMBELL[e] + '{' + s + '}'
    return s


def items_latex(items):
    out, i = [], 0
    while i < len(items):
        n = items[i]
        if n.kind == 'char' and n.tf in (FN_TEXT, FN_TEXT_FE) and n.code and n.code > 0x7F and not n.emb \
                or n.kind == 'char' and n.tf in (FN_TEXT, FN_TEXT_FE) and n.code and chr(n.code).isalpha() and not n.emb:
            # đoạn chữ thường (thường là tiếng Việt) -> \text{}
            j, buf = i, []
            while j < len(items) and items[j].kind == 'char' and items[j].tf in (FN_TEXT, FN_TEXT_FE) and not items[j].emb \
                    and items[j].code and items[j].code < 0xE000:
                buf.append(chr(items[j].code))
                j += 1
            txt = ''.join(buf)
            if txt.strip():
                out.append(r'\text{' + txt.replace('{', r'\{').replace('}', r'\}') + '}')
                i = j
                continue
        if n.kind == 'char' and n.tf == FN_FUNCTION and n.code and chr(n.code).isalpha():
            j, buf = i, []
            while j < len(items) and items[j].kind == 'char' and items[j].tf == FN_FUNCTION \
                    and items[j].code and chr(items[j].code).isalpha():
                buf.append(chr(items[j].code))
                j += 1
            word = ''.join(buf)
            out.append(('\\' + word + ' ') if word in FUNCS else r'\operatorname{' + word + '}')
            i = j
            continue
        out.append(node_latex(n))
        i += 1
    s = ''.join(out)
    return s


def node_latex(n):
    if n.kind == 'line':
        return items_latex(n.items)
    if n.kind == 'char':
        s = char_latex(n)
        if n.tf == FN_VECTOR and s.strip():
            s = r'\mathbf{' + s + '}'
        s = wrap_embell(s, n.emb)
        if s[-1:].isalpha() and s.startswith('\\'):
            s += ' '
        return s
    if n.kind == 'pile':
        rows = [node_latex(x) for x in n.lines if x.kind == 'line']
        al = {1: 'l', 2: 'c', 3: 'r'}.get(n.halign, 'l')
        return r'\begin{array}{' + al + '}' + r' \\ '.join(rows) + r'\end{array}'
    if n.kind == 'matrix':
        cells = [node_latex(x) for x in n.cells if x.kind in ('line', 'pile', 'tmpl')]
        if n.rows == 1 and n.cols == 1 and len(cells) == 1:
            return cells[0]  # ma trận 1x1 chỉ là khung bọc (thường chứa pile của hệ phương trình)
        rows = [' & '.join(cells[k:k + n.cols]) for k in range(0, len(cells), max(n.cols, 1))]
        return r'\begin{matrix}' + r' \\ '.join(rows) + r'\end{matrix}'
    if n.kind == 'tmpl':
        return tmpl_latex(n)
    return ''


def tmpl_latex(n):
    lines = [node_latex(x) for x in n.subs if x.kind == 'line']
    chars = [x for x in n.subs if x.kind == 'char']
    L = lambda k: lines[k] if k < len(lines) else ''
    s, v = n.sel, n.var
    if s in FENCES or s == 9:
        if s == 9:  # interval: lấy ký tự ngoặc thật
            lf = char_latex(chars[0]) if chars else '('
            rf = char_latex(chars[1]) if len(chars) > 1 else ')'
        else:
            lf, rf = FENCES[s]
            if not v & 1: lf = '.'
            if not v & 2: rf = '.'
        return r'\left' + lf + ' ' + L(0) + r' \right' + rf
    if s == 10:  # root
        return (r'\sqrt[' + L(1) + ']{' + L(0) + '}') if v & 1 and L(1) else r'\sqrt{' + L(0) + '}'
    if s == 11:
        return r'\frac{' + L(0) + '}{' + L(1) + '}'
    if s == 12:
        return r'\underline{' + L(0) + '}'
    if s == 13:
        return r'\overline{' + L(0) + '}'
    if s == 14:
        return r'\xrightarrow[' + L(1) + ']{' + L(0) + '}'
    if s in (15, 21):  # integral
        sym = {1: r'\int', 2: r'\iint', 3: r'\iiint'}.get(v & 3, r'\int')
        if v & 4: sym = r'\oint'
        low, up = L(1), L(2)
        out = sym + (('_{' + low + '}') if low else '') + (('^{' + up + '}') if up else '')
        return out + ' ' + L(0)
    if s in BIGOPS or s in (16, 17, 18, 19, 20, 22):
        sym = BIGOPS.get(s, r'\sum')
        if chars:
            c = char_latex(chars[0]).strip()
            if c: sym = c
        low, up = L(1), L(2)
        return sym + (('_{' + low + '}') if low else '') + (('^{' + up + '}') if up else '') + ' ' + L(0)
    if s == 23:  # limit
        return L(0) + (('_{' + L(1) + '}') if L(1) else '') + (('^{' + L(2) + '}') if L(2) else '') + ' '
    if s == 24:
        return r'\underbrace{' + L(0) + '}' + (('_{' + L(1) + '}') if L(1) else '') if v & 1 == 0 else r'\overbrace{' + L(0) + '}^{' + L(1) + '}'
    if s == 25:
        return r'\underbracket{' + L(0) + '}'
    if s == 26:
        return L(1) + r'\,\big)\,' + L(0)
    if s in (27, 28, 29):  # sub/sup: gắn vào phần tử đứng trước
        sub, sup = L(0), L(1)
        return (('_{' + sub + '}') if sub else '') + (('^{' + sup + '}') if sup else '')
    if s == 30:
        return r'\left\langle ' + L(0) + r' \middle| ' + L(1) + r' \right\rangle'
    if s == 31:
        return r'\overrightarrow{' + L(0) + '}'
    if s == 32:
        return r'\widetilde{' + L(0) + '}'
    if s == 33:
        return r'\widehat{' + L(0) + '}'
    if s == 34:
        return r'\overset\frown{' + L(0) + '}'
    if s == 36:
        return r'\cancel{' + L(0) + '}'
    if s == 37:
        return r'\boxed{' + L(0) + '}'
    return ' '.join(lines)


# ---------------------------------------------------------------- API
def mtef_to_latex(data, with_annot=False):
    r = Reader(data)
    parse_header(r)
    nodes = parse_list(r)
    body = tidy(''.join(node_latex(x) for x in nodes))
    if with_annot:
        tex = next((x.tex for x in nodes if x.kind == 'annot'), None)
        return body, tex
    return body


def tidy(s):
    import re
    s = s.replace(r'^{^{\circ}}', r'^{\circ}')
    return re.sub(r'[ \t]+', ' ', s).strip()


def ole_to_latex(blob, with_annot=False):
    """blob: nội dung file word/embeddings/oleObjectN.bin."""
    import io
    ole = olefile.OleFileIO(io.BytesIO(blob))
    if not ole.exists('Equation Native'):
        raise MTEFError('không có stream Equation Native')
    eq = ole.openstream('Equation Native').read()
    hdr = struct.unpack_from('<H', eq, 0)[0]  # EQNOLEFILEHDR, thường 28 byte
    return mtef_to_latex(eq[hdr:], with_annot)
