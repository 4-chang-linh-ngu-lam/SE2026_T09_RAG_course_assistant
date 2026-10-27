import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {MathFormula,ReaderDiagram} from '../src/features/document/reader-content';
test('reader math renders nested fractions with accessible MathML, never executes source markup',()=>{const markup=renderToStaticMarkup(React.createElement(MathFormula,{value:'I\\left(-\\frac{b}{2a};-\\frac{\\Delta}{4a}\\right)'}));assert.equal((markup.match(/<mfrac>/g)??[]).length,2);assert.ok(markup.includes('<mo>Δ</mo>'));assert.ok(!markup.includes('\\frac'));const untrusted=renderToStaticMarkup(React.createElement(MathFormula,{value:'<script>alert(1)</script>'}));assert.ok(!untrusted.includes('<script>'));assert.ok(untrusted.includes('&lt;'));});
test('qualitative source diagram preserves supplied labels and exposes non-scale semantics',()=>{const markup=renderToStaticMarkup(React.createElement(ReaderDiagram,{diagram:{kind:'parabola',title:'Source case',direction:'DOWN',axisLabel:'x = h',vertexLabel:'I(h;k)'}}));assert.ok(markup.includes('I(h;k)'));assert.ok(markup.includes('x = h'));assert.ok(markup.includes('Không theo tỉ lệ'));assert.ok(!markup.includes('y = x'));});
