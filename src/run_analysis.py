"""
Запуск полного анализа: python src/run_analysis.py data/feedback.xlsx

Результаты:
  reports/report.md            — текстовый отчёт со всеми цифрами
  reports/signals.csv          — таблица срезов с приоритетом
  reports/critical_messages.csv — критичные сообщения (без персданных)
  docs/img/*.png               — графики для README
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
import urbanbot as ub  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORTS, IMG = ROOT / "reports", ROOT / "docs" / "img"
RED, GREY, DARK = "#E30611", "#9AA0A6", "#1D2023"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def chart_weekly(df):
    a = df[(df.topic == "Поиск мероприятий") & (df.platform == "Android")]
    wk = a.groupby(["week", a.version == "5.4"])["is_neg"].mean().unstack()
    avg = df.groupby("week")["rating"].mean()
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(wk.index, wk[False] * 100, color=GREY, lw=2, marker="o", label="Поиск, Android 5.2–5.3")
    ax.plot(wk.index, wk[True] * 100, color=RED, lw=2.5, marker="o", label="Поиск, Android 5.4")
    ax.set_ylabel("Доля негатива, %")
    ax2 = ax.twinx()
    ax2.plot(avg.index, avg, color=DARK, lw=1.5, ls="--", label="Средняя оценка сервиса")
    ax2.set_ylim(1, 5); ax2.set_ylabel("Средняя оценка")
    ax.axvline(ub.pd.Timestamp("2026-09-28"), color=RED, alpha=.3, lw=8)
    ax.text(ub.pd.Timestamp("2026-09-29"), 44, "релиз 5.4", color=RED)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="center left", frameon=False, fontsize=9)
    ax.set_title("Средняя оценка почти не двигается, а поиск на Android 5.4 ломается", loc="left")
    for s in ("top",): ax.spines[s].set_visible(False); ax2.spines[s].set_visible(False)
    fig.tight_layout(); fig.savefig(IMG / "android54_search.png", dpi=150); plt.close(fig)


def chart_frequency_vs_severity(ts):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for topic, r in ts.iterrows():
        c = RED if topic == "Покупка и оплата" else (DARK if topic == "Уведомления" else GREY)
        ax.scatter(r.share_of_flow * 100, r.neg_authors_repeat_support * 100, s=r.authors / 3, color=c, alpha=.8)
        ax.annotate(topic, (r.share_of_flow * 100, r.neg_authors_repeat_support * 100),
                    xytext=(8, 4), textcoords="offset points", fontsize=9)
    ax.set_xlabel("Доля от всего потока сообщений, %")
    ax.set_ylabel("Недовольные, повторно обратившиеся\nв поддержку, %")
    ax.set_title("Частота упоминаний ≠ приоритет", loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(IMG / "frequency_vs_severity.png", dpi=150); plt.close(fig)


def main(path: str):
    REPORTS.mkdir(exist_ok=True); IMG.mkdir(parents=True, exist_ok=True)
    df = ub.load(path)
    q = ub.quality_report(df)
    ts = ub.topic_summary(df)
    sig = ub.detect_signals(df)
    crit = ub.critical_messages(df)
    ba = ub.before_after(df, "Поиск мероприятий", "Android", "2026-09-28")

    sig.to_csv(REPORTS / "signals.csv", index=False)
    crit.to_csv(REPORTS / "critical_messages.csv", index=False)
    chart_weekly(df); chart_frequency_vs_severity(ts)

    top = sig[sig.is_signal].head(5)
    lines = [
        "# Отчёт анализа обратной связи", "",
        f"Записей: **{q['rows']}**, авторов: **{q['authors']}**, период: {q['period']}.", "",
        "## Качество данных",
        f"- Оценка заполнена в **{pct(q['rating_filled_share'])}** строк.",
        *[f"  - пустая оценка, {k}: {pct(v)}" for k, v in q["rating_empty_by_source"].items()],
        f"- Авторов с 5+ сообщениями: **{q['authors_with_5plus_messages']}** — считаем уникальных авторов.",
        f"- Без версии приложения: {q['no_version_rows']} строк ({', '.join(q['no_version_platforms'])}).",
        "- Персональные данные (имя, email, телефон) удалены при загрузке.", "",
        "## Темы",
        "| Тема | Доля потока | Авторы | Негатив | Повторно в поддержку (недовольные) | Оценка |",
        "|---|---|---|---|---|---|",
        *[f"| {t} | {pct(r.share_of_flow)} | {int(r.authors)} | {pct(r.neg_share)} | "
          f"{pct(r.neg_authors_repeat_support)} | {r.avg_rating:.2f} |" for t, r in ts.iterrows()],
        "", "## Поиск на Android: до и после 28.09",
        "| Период | Сообщений | Негатив | Оценка |", "|---|---|---|---|",
        *[f"| {p} | {int(r.messages)} | {pct(r.neg_share)} | {r.avg_rating:.2f} |" for p, r in ba.iterrows()],
        "", "## Топ сигналов (окно с 28.09)",
        "| Приоритет | Срез | Негатив | Контроль | Рост | z | Авторы | Повторно в поддержку |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {r.priority} | {r.topic} · {r.platform}{'' if r.version == 'web' else ' ' + r.version} | {pct(r.neg_share)} "
          f"({r.neg_messages}/{r.messages}) | {pct(r.control_neg_share)} | ×{r.lift:.1f} | "
          f"{r.z:.1f} | {r.neg_authors} | {pct(r.repeat_support_share)} |" for r in top.itertuples()],
        "", "## Критичные сообщения (оплата / доступ к билету)",
        f"Найдено **{len(crit)}** сообщений от **{df.loc[df.id.isin(crit.id), 'user_id'].nunique()}** авторов. "
        f"Повторно обратились в поддержку: {pct(crit.repeat_support.mean())}.",
    ]
    (REPORTS / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "feedback.xlsx"))
