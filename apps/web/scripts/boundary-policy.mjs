import ts from 'typescript';

const CONCRETE_UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const FIXTURE_CLASS_ID_REGEX = /^(?:10A[1-9]|9A[1-9])$/;
const FIXED_ISO_DATE_REGEX = /202\d-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d:[0-5]\dZ)?/;
const SCHOOL_YEAR_LITERAL_REGEX = /2026\s*[-–]\s*2027/;

function isUiExampleOrPlaceholder(node) {
  let cur = node.parent;
  while (cur) {
    if (ts.isJsxAttribute(cur) && cur.name && cur.name.text === 'placeholder') return true;
    cur = cur.parent;
  }
  return false;
}

export function inspectSource(name, text) {
  const violations = [];
  const file = ts.createSourceFile(
    name,
    text,
    ts.ScriptTarget.Latest,
    true,
    name.endsWith('tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );
  const fail = message => violations.push(`${name}: ${message}`);

  function inspect(node) {
    const moduleCall =
      node.parent &&
      ts.isCallExpression(node.parent) &&
      (node.parent.expression.kind === ts.SyntaxKind.ImportKeyword ||
        (ts.isIdentifier(node.parent.expression) && node.parent.expression.text === 'require'));

    // Module import boundaries
    if (
      ts.isStringLiteralLike(node) &&
      (ts.isImportDeclaration(node.parent) || ts.isExportDeclaration(node.parent) || moduleCall)
    ) {
      const target = node.text;
      if (/(^|\/)(dev|mocks?|fixtures?)(\/|$)/i.test(target))
        fail('Product code cannot import development fixture modules');
      if (target === '@data-adapter' && name !== 'src/lib/data/index.ts')
        fail('Adapter selection must stay in src/lib/data/index.ts');
      if (/lib\/data\/live(?:$|\.)/.test(target))
        fail('Import the selected data port, not a concrete adapter');
    }

    if (
      ts.isCallExpression(node) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        (ts.isIdentifier(node.expression) && node.expression.text === 'require')) &&
      (!node.arguments[0] || !ts.isStringLiteralLike(node.arguments[0]))
    ) {
      fail('Dynamic module paths cannot bypass import boundaries');
    }

    if (
      ts.isCallExpression(node) &&
      ((ts.isIdentifier(node.expression) && node.expression.text === 'fetch') ||
        (ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'fetch')) &&
      !['src/lib/api/http.ts', 'src/lib/api/proxy.ts'].includes(name)
    ) {
      fail('All network calls belong in the reviewed HTTP transport/proxy');
    }

    if (ts.isIdentifier(node) && ['localStorage', 'sessionStorage'].includes(node.text)) {
      fail('Persistent storage requires a reviewed storage port; never persist credentials');
    }

    // Inline business fixture literals in product source
    const isStringOrJsx =
      ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isJsxText(node);
    if (isStringOrJsx) {
      const val = ts.isJsxText(node) ? node.text.trim() : node.text;
      if (val) {
        const isExample = isUiExampleOrPlaceholder(node) || /(?:ví dụ|example|e\.g\.)/i.test(val);

        // Concrete resource UUID
        if (CONCRETE_UUID_REGEX.test(val)) {
          fail(`Concrete resource UUID fixture found in product code: '${val}'`);
        }

        // Exact fixture class ID (when not a placeholder / example)
        if (!isExample && FIXTURE_CLASS_ID_REGEX.test(val)) {
          fail(`Inline fixture class ID found in product code: '${val}'`);
        }

        // Fixed ISO business date
        if (!isExample && FIXED_ISO_DATE_REGEX.test(val)) {
          fail(`Fixed ISO business date fixture found in product code: '${val}'`);
        }

        // Literal school-year label
        if (!isExample && SCHOOL_YEAR_LITERAL_REGEX.test(val)) {
          fail(`Literal school-year label fixture found in product code: '${val}'`);
        }
      }
    }

    // Static calendar year/month defaults check: { year: 2026, month: 10 }
    if (ts.isObjectLiteralExpression(node)) {
      let hasYearNum = false;
      let hasMonthNum = false;
      for (const prop of node.properties) {
        if (ts.isPropertyAssignment(prop) && ts.isIdentifier(prop.name)) {
          if (prop.name.text === 'year' && ts.isNumericLiteral(prop.initializer)) {
            hasYearNum = true;
          }
          if (prop.name.text === 'month' && ts.isNumericLiteral(prop.initializer)) {
            hasMonthNum = true;
          }
        }
      }
      if (hasYearNum && hasMonthNum) {
        fail('Calendar year/month defaults must derive from context/clock, not static sample values');
      }
    }

    ts.forEachChild(node, inspect);
  }

  inspect(file);
  if (text.includes('__LUMI_PREVIEW_FIXTURE_CANARY_')) fail('Preview fixture marker in product source');
  return violations;
}
