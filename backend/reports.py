"""PDF attendance reports (weekly / monthly) rendered with matplotlib.

Brand-styled A4 pages: summary stats, per-session trend, per-student or
per-subject breakdowns. Returns raw PDF bytes for StreamingResponse.
"""
import io
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

BLURPLE = "#5865F2"
PINK = "#EB459E"
INK = "#14172B"
MUTED = "#5A6080"
OK = "#137A45"
WARN = "#D98E04"
DANGER = "#C22645"
GRID = "#DDE0F0"
TINT = "#EEF0FE"

A4 = (8.27, 11.69)
CUTOFF = 75
PERIODS = {"week": ("Last 7 days", 7), "month": ("Last 30 days", 30)}


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace(" ", "T")).replace(tzinfo=None)
    except ValueError:
        return None


def filter_logs(logs, period):
    label, days = PERIODS.get(period, ("All time", None))
    if days is None:
        return logs, label
    cutoff = datetime.now() - timedelta(days=days)
    kept = [l for l in logs if (parse_ts(l.get("timestamp")) or datetime.min) >= cutoff]
    return kept, label


def _pct_color(pct):
    if pct is None:
        return MUTED
    if pct >= CUTOFF:
        return OK
    if pct >= 50:
        return WARN
    return DANGER


def _sessions(logs):
    """[(time, present, total)] oldest first."""
    groups = {}
    for log in logs:
        key = f"s{log['session_id']}" if log.get("session_id") else f"t{log.get('timestamp')}"
        g = groups.setdefault(key, {"time": parse_ts(log.get("timestamp")), "present": 0, "total": 0})
        g["total"] += 1
        if log.get("is_present"):
            g["present"] += 1
    return sorted(groups.values(), key=lambda g: g["time"] or datetime.min)


def _tile(fig, rect, color):
    """Borderless filled axes (frameon=False would drop the facecolor)."""
    ax = fig.add_axes(rect, xticks=[], yticks=[])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_facecolor(color)
    return ax


def _new_page(title, subtitle):
    fig = plt.figure(figsize=A4)
    fig.patch.set_facecolor("white")
    _tile(fig, [0, 0.955, 1, 0.045], BLURPLE)  # brand band
    fig.text(0.07, 0.925, title, fontsize=20, fontweight="bold", color=INK)
    fig.text(0.07, 0.905, subtitle, fontsize=10.5, color=MUTED)
    fig.text(0.93, 0.925, "SnapClass", fontsize=12, fontweight="bold",
             color=BLURPLE, ha="right")
    fig.text(0.93, 0.905, f"Generated {datetime.now():%d %b %Y, %H:%M}",
             fontsize=8.5, color=MUTED, ha="right")
    return fig


def _stat_boxes(fig, y, stats):
    """Row of stat tiles: [(value, label, color)]."""
    w = 0.86 / len(stats)
    for i, (value, label, color) in enumerate(stats):
        x = 0.07 + i * w
        ax = _tile(fig, [x, y, w - 0.015, 0.075], TINT)
        ax.text(0.5, 0.62, str(value), ha="center", va="center",
                fontsize=17, fontweight="bold", color=color, transform=ax.transAxes)
        ax.text(0.5, 0.2, label, ha="center", va="center",
                fontsize=8.5, color=MUTED, transform=ax.transAxes)


def _style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.grid(True, color=GRID, linewidth=.8)
    ax.set_axisbelow(True)


def _trend_chart(fig, rect, sessions, title):
    ax = fig.add_axes(rect)
    _style_axes(ax)
    ax.set_title(title, fontsize=11, fontweight="bold", color=INK, loc="left", pad=10)
    xs = range(len(sessions))
    pcts = [round(100 * s["present"] / s["total"]) if s["total"] else 0 for s in sessions]
    ax.bar(xs, pcts, width=.62, color=BLURPLE, zorder=3)
    ax.plot(xs, pcts, color=PINK, linewidth=1.6, marker="o", markersize=3.5, zorder=4)
    ax.axhline(CUTOFF, color=DANGER, linewidth=1, linestyle="--", alpha=.7)
    ax.text(len(sessions) - .4, CUTOFF + 2, f"{CUTOFF}%", fontsize=7.5, color=DANGER, ha="right")
    ax.set_ylim(0, 105)
    ax.set_ylabel("% present", fontsize=8.5, color=MUTED)
    labels = [s["time"].strftime("%d %b\n%H:%M") if s["time"] else "?" for s in sessions]
    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels, fontsize=7)
    if len(sessions) > 12:
        for i, tick in enumerate(ax.get_xticklabels()):
            if i % 2:
                tick.set_visible(False)


def _hbar_chart(fig, rect, rows, title):
    """rows: [(name, pct or None)] — horizontal % bars colored by health."""
    ax = fig.add_axes(rect)
    _style_axes(ax)
    ax.xaxis.grid(True, color=GRID, linewidth=.8)
    ax.yaxis.grid(False)
    ax.set_title(title, fontsize=11, fontweight="bold", color=INK, loc="left", pad=10)
    names = [r[0] for r in rows][::-1]
    pcts = [r[1] if r[1] is not None else 0 for r in rows][::-1]
    colors = [_pct_color(r[1]) for r in rows][::-1]
    ax.barh(range(len(rows)), pcts, height=.6, color=colors, zorder=3)
    ax.axvline(CUTOFF, color=DANGER, linewidth=1, linestyle="--", alpha=.7)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlim(0, 105)
    for i, p in enumerate(pcts):
        ax.text(p + 1.5, i, f"{p}%", va="center", fontsize=7.5, color=MUTED)


def _table(fig, rect, headers, rows, col_widths):
    ax = fig.add_axes(rect, frameon=False, xticks=[], yticks=[])
    table = ax.table(cellText=rows, colLabels=headers, colWidths=col_widths,
                     cellLoc="left", loc="upper left")
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_height(0.052)
        cell.PAD = 0.03
        if r == 0:
            cell.set_facecolor(TINT)
            cell.set_text_props(fontweight="bold", color=INK)
        elif r % 2 == 0:
            cell.set_facecolor("#F8F9FE")


def _empty_page(pdf, title, subtitle, label):
    fig = _new_page(title, subtitle)
    fig.text(0.5, 0.5, f"No attendance was taken in this period ({label}).",
             ha="center", fontsize=12, color=MUTED)
    pdf.savefig(fig)
    plt.close(fig)


def build_teacher_report(subject, roster, logs, period):
    """roster: [{student_id, name}], logs: attendance rows for the subject."""
    logs, label = filter_logs(logs, period)
    title = f"{subject['name']} ({subject['subject_code']})"
    subtitle = f"Attendance report - Section {subject.get('section', '-')} - {label}"

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        if not logs:
            _empty_page(pdf, title, subtitle, label)
        else:
            sessions = _sessions(logs)
            per_student = {}
            for log in logs:
                s = per_student.setdefault(log["student_id"], {"attended": 0, "total": 0})
                s["total"] += 1
                s["attended"] += int(bool(log.get("is_present")))
            names = {r["student_id"]: r["name"] for r in roster}
            rows = []
            for sid, s in per_student.items():
                pct = round(100 * s["attended"] / s["total"]) if s["total"] else None
                rows.append((names.get(sid, f"Student {sid}"), pct, s["attended"], s["total"]))
            rows.sort(key=lambda r: (r[1] if r[1] is not None else 101, r[0].lower()))

            avg = round(sum(100 * s["present"] / s["total"] for s in sessions if s["total"]) / len(sessions))
            low = sum(1 for r in rows if r[1] is not None and r[1] < CUTOFF)

            # Page 1: summary + trend
            fig = _new_page(title, subtitle)
            _stat_boxes(fig, 0.79, [
                (len(sessions), "Classes held", INK),
                (f"{avg}%", "Average presence", _pct_color(avg)),
                (len(rows), "Students tracked", INK),
                (low, f"Below {CUTOFF}%", DANGER if low else OK),
            ])
            _trend_chart(fig, [0.09, 0.45, 0.84, 0.26], sessions, "Presence per class")
            n = min(len(rows), 18)
            _hbar_chart(fig, [0.22, 0.06, 0.71, min(0.33, 0.018 * n + 0.04)],
                        [(r[0], r[1]) for r in rows[:18]],
                        f"Per-student attendance{' (lowest 18)' if len(rows) > 18 else ''}")
            pdf.savefig(fig)
            plt.close(fig)

            # Page 2+: full table, 28 rows per page
            CHUNK = 28
            for start in range(0, len(rows), CHUNK):
                chunk = rows[start:start + CHUNK]
                fig = _new_page(title, f"{subtitle} - Student detail")
                _table(fig, [0.07, 0.08, 0.86, 0.78],
                       ["Student", "Attended", "Classes", "Rate", "Status"],
                       [[r[0], r[2], r[3],
                         f"{r[1]}%" if r[1] is not None else "-",
                         ("LOW" if r[1] is not None and r[1] < CUTOFF else "OK")] for r in chunk],
                       [0.4, 0.14, 0.14, 0.14, 0.18])
                pdf.savefig(fig)
                plt.close(fig)
    return buf.getvalue()


def build_student_report(student, logs, period):
    """logs: student's attendance rows joined with subject(*)."""
    logs, label = filter_logs(logs, period)
    title = student["name"]
    subtitle = f"My attendance report - {label}"

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        if not logs:
            _empty_page(pdf, title, subtitle, label)
        else:
            per_subject = {}
            for log in logs:
                sub = log.get("subject") or {}
                key = log["subject_id"]
                s = per_subject.setdefault(key, {
                    "name": sub.get("name", f"Subject {key}"),
                    "code": sub.get("subject_code", ""),
                    "attended": 0, "total": 0,
                })
                s["total"] += 1
                s["attended"] += int(bool(log.get("is_present")))
            rows = []
            for s in per_subject.values():
                pct = round(100 * s["attended"] / s["total"]) if s["total"] else None
                rows.append((f"{s['name']} ({s['code']})", pct, s["attended"], s["total"]))
            rows.sort(key=lambda r: r[0].lower())

            total = sum(r[3] for r in rows)
            attended = sum(r[2] for r in rows)
            overall = round(100 * attended / total) if total else 0

            # Daily presence timeline
            by_day = {}
            for log in logs:
                t = parse_ts(log.get("timestamp"))
                if not t:
                    continue
                d = by_day.setdefault(t.date(), {"time": datetime.combine(t.date(), datetime.min.time()),
                                                 "present": 0, "total": 0})
                d["total"] += 1
                d["present"] += int(bool(log.get("is_present")))
            days = sorted(by_day.values(), key=lambda d: d["time"])

            fig = _new_page(title, subtitle)
            _stat_boxes(fig, 0.79, [
                (total, "Classes held", INK),
                (attended, "Attended", OK),
                (f"{overall}%", "Overall rate", _pct_color(overall)),
                (len(rows), "Subjects", INK),
            ])
            _trend_chart(fig, [0.09, 0.45, 0.84, 0.26], days, "Presence by day")
            _hbar_chart(fig, [0.26, 0.08, 0.67, min(0.3, 0.03 * len(rows) + 0.05)],
                        [(r[0], r[1]) for r in rows], "Attendance per subject")
            pdf.savefig(fig)
            plt.close(fig)

            fig = _new_page(title, f"{subtitle} - Subject detail")
            _table(fig, [0.07, 0.08, 0.86, 0.78],
                   ["Subject", "Attended", "Classes", "Rate", "Status"],
                   [[r[0], r[2], r[3],
                     f"{r[1]}%" if r[1] is not None else "-",
                     ("LOW" if r[1] is not None and r[1] < CUTOFF else "OK")] for r in rows],
                   [0.4, 0.14, 0.14, 0.14, 0.18])
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()
