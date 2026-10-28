"""
Урбанбот — детектор сигналов в пользовательской обратной связи.

Идея: продакту нужна не средняя оценка, а ответ на три вопроса:
появилось ли изменение, чего оно касается и почему его стоит считать важным.

Модуль:
  load()            — загрузка выгрузки и маскирование персональных данных
  quality_report()  — проверка качества данных (пустые оценки, дубли, версии)
  topic_summary()   — сводка по темам: объём, авторы, негатив, повторные обращения
  detect_signals()  — сравнение срезов «тема × платформа × версия» с контрольной группой
  critical_messages() — отбор редких критичных сообщений (оплата / доступ к билету)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

PII_COLUMNS = ["user_name", "email", "phone"]
NEG = "Негативный"

# Сценарии, где ошибка стоит денег или лишает пользователя доступа к событию.
CRITICAL_PATTERNS = re.compile(
    r"оплачено|платёж прош|оплата прош.*(?:не|нет)|статус оплаты|заказ исчез|"
    r"нет билета|отсутствующ\w* билет|доступ не откр|не смог найти оформленн|"
    r"купить тот же билет|qr-код.*не загруз|не пускают|не пустили",
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------- загрузка
def load(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="feedback_data")
    df = df.drop(columns=[c for c in PII_COLUMNS if c in df.columns])
    df["date"] = pd.to_datetime(df["date"])
    df["week"] = df["date"].dt.to_period("W").dt.start_time
    df["version"] = df["app_version"].map(lambda v: "web" if pd.isna(v) else f"{v:.1f}")
    df["is_neg"] = df["sentiment"].eq(NEG)
    df["repeat_support"] = df["additional_support_contact"].eq("Да")
    return df


def mask_text(text: str) -> str:
    """Убирает из текста email и телефоны перед показом или отправкой в модель."""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", str(text))
    return re.sub(r"\+?\d[\d\s()-]{8,}\d", "[phone]", text)


# ---------------------------------------------------------- качество данных
def quality_report(df: pd.DataFrame) -> dict:
    by_source = df.groupby("source")["rating"].apply(lambda s: s.isna().mean())
    per_user = df["user_id"].value_counts()
    return {
        "rows": len(df),
        "authors": df["user_id"].nunique(),
        "period": f"{df['date'].min():%d.%m.%Y} – {df['date'].max():%d.%m.%Y}",
        "rating_filled_share": df["rating"].notna().mean(),
        "rating_empty_by_source": by_source.to_dict(),
        "authors_with_5plus_messages": int((per_user >= 5).sum()),
        "no_version_rows": int(df["app_version"].isna().sum()),
        "no_version_platforms": df.loc[df["app_version"].isna(), "platform"].unique().tolist(),
    }


# ------------------------------------------------------------ сводка по темам
def topic_summary(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("topic").agg(
        messages=("id", "size"),
        authors=("user_id", "nunique"),
        neg_share=("is_neg", "mean"),
        repeat_support_share=("repeat_support", "mean"),
        avg_rating=("rating", "mean"),
    )
    g["share_of_flow"] = g["messages"] / len(df)
    neg = df[df["is_neg"]]
    g["neg_authors_repeat_support"] = neg.groupby("topic")["repeat_support"].mean()
    return g.sort_values("messages", ascending=False)


# --------------------------------------------------------- детектор сигналов
def _two_prop_z(k1: int, n1: int, k2: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 0.0
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-9
    return (k1 / n1 - k2 / n2) / se


@dataclass
class SignalConfig:
    start: str = "2026-09-28"      # начало окна наблюдения (неделя релиза 5.4)
    end: str | None = None
    min_messages: int = 30         # меньше — слишком шумно
    min_lift: float = 1.5          # негатив хотя бы в 1,5 раза выше контроля
    min_z: float = 2.0             # статистическая значимость (~95%)


def detect_signals(df: pd.DataFrame, cfg: SignalConfig = SignalConfig()) -> pd.DataFrame:
    """
    Каждый срез «тема × платформа × версия» в окне сравнивается с контролем:
    той же темой на остальных срезах за тот же период. Так локальная поломка
    не растворяется в среднем по сервису.
    """
    w = df[df["date"] >= cfg.start]
    if cfg.end:
        w = w[w["date"] <= cfg.end]

    base_support = df["repeat_support"].mean()
    rows = []
    for (topic, platform, version), s in w.groupby(["topic", "platform", "version"]):
        ctrl = w[(w["topic"] == topic) & ~((w["platform"] == platform) & (w["version"] == version))]
        k1, n1 = int(s["is_neg"].sum()), len(s)
        k2, n2 = int(ctrl["is_neg"].sum()), len(ctrl)
        if n1 < cfg.min_messages:
            continue
        p1, p2 = k1 / n1, (k2 / n2 if n2 else 0)
        lift = p1 / p2 if p2 else np.inf
        z = _two_prop_z(k1, n1, k2, n2)
        neg = s[s["is_neg"]]
        rows.append({
            "topic": topic, "platform": platform, "version": version,
            "messages": n1, "neg_messages": k1, "neg_authors": neg["user_id"].nunique(),
            "neg_share": p1, "control_neg_share": p2, "lift": lift, "z": z,
            "repeat_support_share": neg["repeat_support"].mean() if len(neg) else 0.0,
            "first_seen": s["date"].min().date(),
        })
    out = pd.DataFrame(rows)
    out["is_signal"] = (out["lift"] >= cfg.min_lift) & (out["z"] >= cfg.min_z)
    out["priority"] = _priority(out, base_support)
    return out.sort_values(["is_signal", "priority"], ascending=False).reset_index(drop=True)


def _priority(t: pd.DataFrame, base_support: float) -> pd.Series:
    """
    Прозрачная формула приоритета (0–100). Веса — стартовые, на пилоте их
    калибруют по экспертной разметке:
      40 — отклонение от контроля (lift, ограничен 4x)
      30 — тяжесть: доля повторных обращений в поддержку к норме (ограничена 4x)
      20 — масштаб: число уникальных авторов (лог-шкала)
      10 — значимость (z, ограничен 4)
    """
    lift = (t["lift"].clip(upper=4) - 1).clip(lower=0) / 3
    sev = (t["repeat_support_share"] / base_support).clip(upper=4) / 4
    scale = np.log1p(t["neg_authors"]) / np.log1p(t["neg_authors"].max() or 1)
    sig = t["z"].clip(lower=0, upper=4) / 4
    return (40 * lift + 30 * sev + 20 * scale + 10 * sig).round(1)


# ------------------------------------------------------ критичные сообщения
def critical_messages(df: pd.DataFrame) -> pd.DataFrame:
    """Редкие, но тяжёлые случаи: деньги списаны, а доступа к событию нет."""
    m = df["is_neg"] & df["text"].str.contains(CRITICAL_PATTERNS)
    out = df.loc[m, ["id", "date", "topic", "platform", "version", "source",
                     "repeat_support", "text"]].copy()
    out["text"] = out["text"].map(mask_text)
    return out.sort_values("date")


def before_after(df: pd.DataFrame, topic: str, platform: str, release: str) -> pd.DataFrame:
    s = df[(df["topic"] == topic) & (df["platform"] == platform)]
    s = s.assign(period=np.where(s["date"] >= release, "после", "до"))
    return s.groupby("period").agg(
        messages=("id", "size"), neg_share=("is_neg", "mean"), avg_rating=("rating", "mean")
    ).reindex(["до", "после"])
