'use client';
import React, {useId,type ReactNode} from 'react';
import type {DocumentDiagram} from '@/lib/domain';
type MathProps = React.Attributes & React.HTMLAttributes<MathMLElement> & {xmlns?:string; mathvariant?:string; width?:string};
declare module 'react' { namespace JSX { interface IntrinsicElements {math:MathProps;mi:MathProps;mo:MathProps;mn:MathProps;mrow:MathProps;mfrac:MathProps;msqrt:MathProps;mtext:MathProps;mspace:MathProps;msup:MathProps;msub:MathProps;} } }

// A deliberately small, non-HTML math renderer for the supported source notation.
// All strings remain React text; no arbitrary markup/scripts or expression eval.
export function MathFormula({value}:{value:string}){
 let index=0;
 function group():ReactNode[]{if(value[index]==='{'){index++;const result=parse('}');if(value[index]==='}')index++;return result;}const c=value[index++];return c?[<mi key={`c${index}`}>{c}</mi>]:[];}
 function parse(end?:string):ReactNode[]{const nodes:ReactNode[]=[];while(index<value.length&&value[index]!==end){const start=index;let node:ReactNode;const c=value[index++];
  if(c==='\\'){
   const command=/^[A-Za-z]+/.exec(value.slice(index))?.[0]??'';index+=command.length;
   if(command==='frac'){const numerator=group();const denominator=group();node=<mfrac key={start}><mrow>{numerator}</mrow><mrow>{denominator}</mrow></mfrac>;}
   else if(command==='sqrt')node=<msqrt key={start}><mrow>{group()}</mrow></msqrt>;
   else if(command==='text')node=<mtext key={start}>{textGroup()}</mtext>;
   else if(command==='mathbb')node=<mi key={start} mathvariant="double-struck">{textGroup()}</mi>;
   else if(command==='left'||command==='right')continue;
   else if(command==='quad'||command==='qquad')node=<mspace key={start} width="1em"/>;
   else {const symbols:Record<string,string>={Delta:'Δ',delta:'δ',alpha:'α',beta:'β',gamma:'γ',pi:'π',theta:'θ',infty:'∞',neq:'≠',leq:'≤',geq:'≥',in:'∈',mathbb:'',cdot:'·',times:'×',searrow:'↘',nearrow:'↗'};node=<mo key={start}>{symbols[command]??command??'\\'}</mo>;}
  }else if(c==='{' ){node=<mrow key={start}>{parse('}')}</mrow>;if(value[index]==='}')index++;}
  else if(c==='^'||c==='_'){const previous=nodes.pop()??<mrow/>;const script=group();node=c==='^'?<msup key={start}><mrow>{previous}</mrow><mrow>{script}</mrow></msup>:<msub key={start}><mrow>{previous}</mrow><mrow>{script}</mrow></msub>;}
  else if(/\s/.test(c)){continue;}
  else if(/[0-9.]/.test(c)){let n=c;while(index<value.length&&/[0-9.]/.test(value[index]))n+=value[index++];node=<mn key={start}>{n}</mn>;}
  else if(/[A-Za-z]/.test(c))node=<mi key={start}>{c}</mi>;
  else node=<mo key={start}>{c}</mo>;
  nodes.push(node);
 }return nodes;}
 function textGroup(){if(value[index]!=='{')return value[index++]??'';index++;let text='';let depth=1;while(index<value.length&&depth){const c=value[index++];if(c==='{')depth++;else if(c==='}')depth--;if(depth)text+=c;}return text;}
 return <math xmlns="http://www.w3.org/1998/Math/MathML" className="reader-math" aria-label={mathText(value)}><mrow>{parse()}</mrow></math>;
}
export function mathText(value:string):string{return value.replace(/\\left|\\right/g,'').replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g,'($1)/($2)').replace(/\\Delta/g,'Δ').replace(/\\neq/g,'≠').replace(/\\mathbb\{R\}/g,'ℝ').replace(/\\(?:quad|qquad)/g,' ').replace(/\\text\{([^{}]*)\}/g,'$1').replace(/\\searrow/g,'↘').replace(/\\nearrow/g,'↗').replace(/[{}]/g,'');}
export function ReaderDiagram({diagram}:{diagram:DocumentDiagram}){
 const id=useId();
 if(diagram.kind==='variation')return <figure className="reader-diagram"><figcaption>{diagram.title}</figcaption><div className="reader-variation" role="img" aria-label={`${diagram.title}: ${diagram.xLabels.join(', ')}; ${diagram.directions.map(d=>d==='UP'?'đồng biến':'nghịch biến').join(' rồi ')}; ${diagram.extremumLabel}`}><div>x</div>{diagram.xLabels.map((label,i)=><div key={i}>{label}</div>)}<div>y</div><div className="variation-arrow">{diagram.directions[0]==='UP'?'↗':'↘'}</div><div>{diagram.extremumLabel}</div><div className="variation-arrow">{diagram.directions[1]==='UP'?'↗':'↘'}</div></div></figure>;
 const up=diagram.direction==='UP';const vertexY=up?118:76;
 return <figure className={`reader-diagram ${up?'up':'down'}`}><figcaption>{diagram.title}</figcaption><svg viewBox="0 0 320 210" role="img" aria-labelledby={`${id}-title ${id}-description`}><title id={`${id}-title`}>{diagram.title}</title><desc id={`${id}-description`}>Sơ đồ định tính của parabol. {diagram.vertexLabel}. Trục đối xứng {diagram.axisLabel}. Không theo tỉ lệ.</desc><defs><marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="#64748b"/></marker></defs><path d="M32 168H298 M78 188V20" stroke="#94a3b8" strokeWidth="1.5" markerEnd={`url(#${id}-arrow)`}/><text x="300" y="181">x</text><text x="64" y="19">y</text><text x="64" y="182">O</text><path d={up?'M40 40 Q160 196 280 40':'M40 154 Q160 -2 280 154'} fill="none" stroke={up?'#2563eb':'#c2410c'} strokeWidth="3"/><path d="M160 24V186" stroke="#2563eb" strokeDasharray="4 4"/><circle cx="160" cy={vertexY} r="4" fill={up?'#2563eb':'#c2410c'}/><text x="171" y={vertexY-10} className="diagram-vertex">I</text><text x="165" y="201" className="diagram-axis">{diagram.axisLabel}</text></svg><p>{diagram.vertexLabel}</p><small>Sơ đồ định tính, không theo tỉ lệ.</small></figure>;
}
