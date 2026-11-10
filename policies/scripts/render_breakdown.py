"""Render the rule/check breakdown for a policy rules file and refresh the generated judge section.

Usage: python policies/scripts/render_breakdown.py policies/osu/osu_rules.yaml

- Writes rule_breakdown.png next to the rules file.
- Prints the breakdown tables as markdown (for policies/README.md).
- If <org>_policy.md sits next to the rules file and contains the GENERATED markers, rewrites the
  judge-checks section between them from the YAML, so it can never drift from the rules.
"""
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import yaml

# inputs, in the order a deployment is likely to gain them
TIERS = ['transaction', 'table', 'records', 'receipt']
SCENARIOS = ['Transaction fields only', '+ reference tables', '+ OSU system records', '+ receipts']
PATTERNS = ['threshold', 'list_membership', 'line_item', 'document_presence', 'aggregation', 'cross_reference', 'purpose']
METHOD_COLORS = {'code': '#2a78d6', 'llm': '#eb6834'}
INK, MUTED, GRID = '#0b0b0b', '#52514e', '#e6e6e6'
BEGIN, END = '<!-- BEGIN GENERATED: judge checks -->', '<!-- END GENERATED: judge checks -->'


def tier(check):
    """Most demanding input a check needs."""
    kinds = {r.split(':')[0] for r in check['requires']}
    for t in reversed(TIERS):
        if t in kinds:
            return t
    return 'transaction'


def style(ax):
    ax.grid(True, axis='x', color=GRID)
    ax.set_axisbelow(True)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color('#bdbdbd')
    ax.tick_params(colors=MUTED)


def stacked_barh(ax, labels, counts_by_method):
    for i in range(len(labels)):
        left = 0
        for m in ('code', 'llm'):
            n = counts_by_method[m][i]
            if n:
                ax.barh(i, n, left=left, color=METHOD_COLORS[m], edgecolor='white', linewidth=2, height=0.62)
                if n >= 3:
                    ax.text(left + n / 2, i, str(n), ha='center', va='center', fontsize=9, color='white')
                else:  # too thin to label inside: put the count just above the segment
                    ax.text(left + n / 2, i - 0.36, str(n), ha='center', va='bottom', fontsize=8, color=MUTED)
                left += n
        ax.text(left + 0.8, i, str(left), va='center', fontsize=9, color=MUTED)
    ax.set_yticks(range(len(labels)), labels, fontsize=9)
    ax.invert_yaxis()


def main(path):
    path = Path(path)
    doc = yaml.safe_load(path.read_text())
    rules, cats = doc['rules'], doc['categories']
    checks = [dict(c, rule=r) for r in rules for c in r['checks']]
    rank = {t: i for i, t in enumerate(TIERS)}

    # cumulative: checks runnable once the inputs up to each scenario exist
    runnable = {m: [sum(1 for c in checks if c['method'] == m and rank[tier(c)] <= i) for i in range(len(TIERS))]
                for m in ('code', 'llm')}
    by_pattern = {m: [sum(1 for c in checks if c['method'] == m and c['pattern'] == p) for p in PATTERNS]
                  for m in ('code', 'llm')}
    per_cat = Counter(a for r in rules for a in r['applies_to'])

    fig, ax = plt.subplots(1, 3, figsize=(19, 5.6), gridspec_kw={'width_ratios': [1, 1, 1.1]})

    stacked_barh(ax[0], SCENARIOS, runnable)
    ax[0].set_xlim(0, len(checks) + 12)
    ax[0].set_xlabel(f'checks that can run (of {len(checks)})', color=MUTED)
    ax[0].set_title('Checks that can run as inputs are added', loc='left', color=INK)

    stacked_barh(ax[1], [p.replace('_', ' ') for p in PATTERNS], by_pattern)
    ax[1].set_xlim(0, max(sum(x) for x in zip(*by_pattern.values())) + 6)
    ax[1].set_xlabel('checks', color=MUTED)
    ax[1].set_title('Checks by question pattern', loc='left', color=INK)
    handles = [plt.Rectangle((0, 0), 1, 1, color=METHOD_COLORS[m]) for m in ('code', 'llm')]
    fig.legend(handles, ['Code check (deterministic)', 'LLM judge'], frameon=False, ncol=2, fontsize=9,
               loc='upper right', bbox_to_anchor=(0.995, 0.995))

    order = ['all'] + sorted((c for c in cats if per_cat[c]), key=lambda c: -per_cat[c])
    vals = [per_cat[c] for c in order]
    bars = ax[2].barh(range(len(order)), vals, color=['#52514e'] + ['#2a78d6'] * (len(order) - 1), height=0.65)
    for b, v in zip(bars, vals):
        ax[2].text(v + 0.3, b.get_y() + b.get_height() / 2, str(v), va='center', fontsize=9, color=MUTED)
    ax[2].set_yticks(range(len(order)), ['All categories' if c == 'all' else cats[c] for c in order], fontsize=9)
    ax[2].invert_yaxis()
    ax[2].set_xlabel('rules that apply (a rule can apply to several)', color=MUTED)
    ax[2].set_title('Rules routed to each expense category', loc='left', color=INK)

    for a in ax:
        style(a)
    fig.suptitle(f"{doc['policy']['name']} ({doc['policy']['version']}): {len(rules)} rules, {len(checks)} checks",
                 x=0.01, ha='left', fontsize=12, color=INK)
    plt.tight_layout()
    out = path.parent / 'rule_breakdown.png'
    fig.savefig(out, dpi=150, facecolor='white')

    # ---- markdown tables for the README
    n = len(checks)
    print('| Inputs available | Code checks | LLM checks | Total runnable | Share of checks |')
    print('|---|---|---|---|---|')
    for i, s in enumerate(SCENARIOS):
        c, l = runnable['code'][i], runnable['llm'][i]
        print(f'| {s} | {c} | {l} | {c + l} | {(c + l) / n:.0%} |')
    print('\n| Pattern | Code | LLM | Total |\n|---|---|---|---|')
    for i, p in enumerate(PATTERNS):
        c, l = by_pattern['code'][i], by_pattern['llm'][i]
        print(f'| {p} | {c} | {l} | {c + l} |')
    print(f'| **Total** | **{sum(by_pattern["code"])}** | **{sum(by_pattern["llm"])}** | **{n}** |')
    print(f'\nwrote {out}')

    # ---- generated judge section in the condensed policy
    md = next(path.parent.glob('*_policy.md'), None)
    if md and BEGIN in md.read_text():
        text = md.read_text()
        a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
        md.write_text(text[:a] + '\n' + judge_section(rules) + text[b:])
        print(f'refreshed judge section in {md}')


def judge_section(rules):
    lines = ['_Generated from the rules file by `policies/scripts/render_breakdown.py`. Edit the YAML, not this section._', '']
    for topic in ('limits', 'vendor', 'process', 'items', 'travel'):
        llm = [(r, c) for r in rules if r['topic'] == topic for c in r['checks'] if c['method'] == 'llm']
        if not llm:
            continue
        lines += [f'### {topic.capitalize()}', '']
        for r, c in llm:
            lines.append(f"**{c['id']}** ({r['title']}): {c['ask']}.")
            if c.get('when'):
                w = c['when']
                refs = ' or '.join(w.get('any_of') or [w['check']])
                lines.append(f"- *Sent to you when:* {refs} returned `{str(w['result']).lower()}`")
            if c.get('screen'):
                lines.append(f"- *Sent to you when:* {c['screen']['match']}")
            for k in ('violation', 'flag', 'allowed', 'unclear'):
                if k in c['decision']:
                    lines.append(f"- *{k.capitalize()}:* {c['decision'][k]}")
            lines.append('')
    return '\n'.join(lines)


if __name__ == '__main__':
    main(sys.argv[1])
