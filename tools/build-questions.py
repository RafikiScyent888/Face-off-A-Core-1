#!/usr/bin/env python3
"""
Build questions-core1.js from the Core-1-quizzes practice bank.

Source: https://rafikiscyent888.github.io/Core-1-quizzes/

Each quiz sub-objective becomes one Face-Off category, and the correct
multiple-choice option becomes the answer key the host sees. Clues inside a
category are ordered easiest -> hardest, which is what the board expects:
row 1 is the cheapest clue, the last row the dearest.

Usage:  python3 tools/build-questions.py [path-to-Core-1-quizzes]
        Defaults to ../Core-1-quizzes — the quiz repo checked out alongside this one.
"""
import json, os, re, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUIZ = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "Core-1-quizzes")
OUT   = os.path.join(HERE, "questions-core1.js")
TITLE = "A+ CORE 1"
EXAM  = "CompTIA A+ 220-1201 (Core 1)"
SITE  = "https://rafikiscyent888.github.io/Core-1-quizzes/"


def node_json(src_path, expr):
    """Evaluate a quiz site's JS bundle and hand the data back as JSON."""
    # the expression is concatenated INTO the eval: CySA's bundle uses `const`,
    # which is block-scoped to the eval and invisible to a later statement
    js = ('var fs=require("fs");var src=fs.readFileSync(%s,"utf8");'
          'global.window=global.window||{};var out;'
          'eval(src + ";out = " + %s + ";");'
          'process.stdout.write(JSON.stringify(out));'
          % (json.dumps(src_path), json.dumps(expr)))
    out = subprocess.run(['node', '-e', js], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit('node failed on %s:\n%s' % (src_path, out.stderr[:800]))
    return json.loads(out.stdout)


def load_core1(QUIZ):
    """A+ Core 1 — a <script id="question-data"> JSON block, same as Core 2."""
    html = open(os.path.join(QUIZ, 'index.html'), encoding='utf-8').read()
    bank = json.loads(re.search(
        r'<script[^>]*id="question-data"[^>]*>(.*?)</script>', html, re.S).group(1))
    block = re.search(r'const SUB_OBJECTIVES = \{(.*?)\n\};', html, re.S).group(1)
    labels, order, cur = {}, [], None
    for line in block.splitlines():
        dom = re.match(r'\s*"([^"]+)":\s*\[', line)
        if dom:
            cur = dom.group(1)
            continue
        sub = re.match(r'\s*\{\s*id:\s*"([^"]+)",\s*label:\s*"([^"]+)"', line)
        if sub:
            labels[sub.group(1)] = sub.group(2)
            order.append((cur, sub.group(1)))
    rows = [{'q': q['q'], 'a': q['choices'][q['correct']], 'sub': q['sub']}
            for q in bank if q.get('sub') in labels]
    return order, labels, rows


def tidy(s):
    s = unicodedata.normalize('NFC', s or '')
    s = (s.replace('\u2018', "'").replace('\u2019', "'")
          .replace('\u201c', '"').replace('\u201d', '"')
          .replace('\u2014', ' \u2014 ').replace('\u00a0', ' '))
    return re.sub(r'\s+', ' ', s).strip()


def answer_text(choice):
    a = tidy(choice)
    if a.endswith('.') and not a.endswith('..'):
        a = a[:-1]
    return a


def js(s):
    return json.dumps(s, ensure_ascii=False)


def build(order, labels, rows):
    """Group into categories, order each easiest-first, interleave domains."""
    by_sub = {}
    for r in rows:
        text, ans = tidy(r['q']), answer_text(r['a'])
        if text and ans:
            by_sub.setdefault(r['sub'], []).append(
                {'q': text, 'a': ans, 'obj': r['sub'], 'w': len(text) + 2 * len(ans)})

    domains, seen = [], set()
    for dom, _ in order:
        if dom not in seen:
            seen.add(dom); domains.append(dom)
    per_domain = {d: [s for dd, s in order if dd == d and by_sub.get(s)] for d in domains}

    cats = []
    while any(per_domain.values()):
        for d in domains:
            if per_domain[d]:
                sub = per_domain[d].pop(0)
                clues = sorted(by_sub[sub], key=lambda c: (c['w'], c['q']))
                for c in clues:
                    del c['w']
                cats.append({'name': labels[sub].upper(), 'obj': sub,
                             'domain': d, 'clues': clues})

    # Lightning Final: ten seconds a question, so what matters is a SHORT
    # question the host can read fast. A long answer key is fine — the host
    # is judging, not reading it out. CySA's bank in particular pairs short
    # scenarios with long option text, and an answer-length filter left it
    # with no lightning questions at all. Two per category, shortest first,
    # falling back to a category's shortest if none clear the bar.
    lightning = []
    for cat in cats:
        ranked = sorted(cat['clues'], key=lambda c: (len(c['q']), len(c['a'])))
        picked = [c for c in ranked if len(c['q']) <= 175][:2] or ranked[:1]
        lightning.extend(picked)
    lightning.sort(key=lambda c: len(c['q']))
    return cats, lightning


HEADER = '''/* =====================================================================
   FACE-OFF: %(title)s  \u2014  QUESTION POOL
   Exam: %(exam)s
   ---------------------------------------------------------------------
   GENERATED FILE \u2014 do not hand-edit unless you mean to.

   Every clue below is pulled straight from the practice bank at
   %(site)s
   \u2014 the same questions students drill on their own. Each quiz
   sub-objective becomes one category, and the correct multiple-choice
   option becomes the answer key the host sees.

     \u2022 %(ncats)d categories \u00b7 %(nclues)d clues \u00b7 %(nlight)d lightning questions
     \u2022 Each category's clues run EASIEST (first) to HARDEST (last)
     \u2022 The game draws unused clues each round, so no repeats in a game

   Clue shape
     q   = the question students see
     a   = the answer (host screen only, hidden until the host reveals it)
     alt = other phrasings you'd accept (host hint, optional)
     obj = objective number

   Regenerate with tools/build-questions.py after the quiz bank changes.
   ===================================================================== */

window.FACEOFF_QUESTIONS = {
  exam: %(examjs)s,

  categories: [
'''


def render(title, exam, site, cats, lightning):
    out = [HEADER % dict(title=title, exam=exam, site=site, examjs=js(exam),
                         ncats=len(cats),
                         nclues=sum(len(c['clues']) for c in cats),
                         nlight=len(lightning))]
    for n, cat in enumerate(cats, 1):
        out.append('\n  /* ============ %d \u00b7 %s ============ */\n' % (n, cat['domain']))
        out.append('  { name: %s, obj: %s, clues: [\n' % (js(cat['name']), js(cat['obj'])))
        out.append(',\n'.join(
            '    { q: %s,\n      a: %s, obj: %s }' % (js(c['q']), js(c['a']), js(c['obj']))
            for c in cat['clues']))
        out.append('\n  ]}%s\n' % (',' if n < len(cats) else ''))
    out.append('''
  ],

  /* =====================================================================
     LIGHTNING FINAL \u2014 head-to-head between the last two teams.
     The shortest question/answer pairs in the bank, spread across objectives.
     ===================================================================== */
  lightning: [
''')
    out.append(',\n'.join(
        '    { q: %s,\n      a: %s, obj: %s }' % (js(c['q']), js(c['a']), js(c['obj']))
        for c in lightning))
    out.append('\n  ]\n};\n')
    return ''.join(out)


if __name__ == "__main__":
    if not os.path.isdir(QUIZ):
        raise SystemExit("quiz bank not found at %s\n"
                         "pass its path: python3 tools/build-questions.py <path>" % QUIZ)
    order, labels, rows = load_core1(QUIZ)
    cats, lightning = build(order, labels, rows)
    open(OUT, "w", encoding="utf-8").write(render(TITLE, EXAM, SITE, cats, lightning))
    print("%d categories  %d clues  %d lightning"
          % (len(cats), sum(len(c["clues"]) for c in cats), len(lightning)))
