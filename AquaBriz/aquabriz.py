#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AquaBriz — профессиональное настольное приложение для учета расхода воды.
Один файл .py, продуманная архитектура, VIP-функции, экспорт, графики, советы.

Компоненты:
- AquaBrizApp — интерфейс
- DatabaseManager — хранение данных (SQLite)
- StatisticsEngine — расчёты статистики
- GraphEngine — построение графиков (matplotlib)
- VIPManager — проверка VIP-кода и контроль доступа
- ExportEngine — экспорт данных (CSV, Excel, PDF)
- AdviceEngine — советы по экономии и анализ утечек
- SettingsManager — настройки (единицы, нормы, уведомления, тема)
- LogManager — логирование всех действий

Зависимости:
- tkinter, ttk, sqlite3 — стандартная библиотека
- matplotlib — графики
- pandas, openpyxl — экспорт в Excel
- reportlab — экспорт в PDF

Программа запускается сразу.
"""

import os
import sys
import sqlite3
import json
import math
import datetime as dt
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

# GUI
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Data & Export
import csv
import pandas as pd

# PDF
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

# Numpy-lite for regression (avoid hard dep). We'll implement simple linear regression manually.
# If numpy is available, we can use it; otherwise fall back.
try:
    import numpy as np
except Exception:
    np = None


# ------------------------------ Constants & Theme ------------------------------

APP_NAME = "AquaBriz"
APP_VERSION = "1.0.0"
VIP_CODE = "VIP-1685"

# Brand colors
BRAND_1 = "#00b4d8"  # accent
BRAND_2 = "#0096c7"  # primary
BRAND_3 = "#023e8a"  # deep blue
BRAND_4 = "#03045e"  # very deep blue

BG_LIGHT = "#f7fbff"
TEXT_COLOR = "#0b1b3a"

DB_FILE = "aquabriz.db"
LOG_FILE = "aquabriz.log"
SETTINGS_FILE = "aquabriz_settings.json"

# ------------------------------ Utilities ------------------------------

def safe_float(value: str) -> Optional[float]:
    try:
        v = float(str(value).replace(",", "."))
        return v
    except Exception:
        return None

def fade_in_window(win: tk.Toplevel, duration_ms: int = 250):
    """
    Плавное появление окна за duration_ms миллисекунд.
    """
    steps = 12
    interval = max(10, duration_ms // steps)
    win.attributes("-alpha", 0.0)
    def step(i=0):
        if i <= steps:
            alpha = i / steps
            win.attributes("-alpha", alpha)
            win.after(interval, step, i + 1)
    step()

def add_hover_effect(widget: tk.Widget, normal_bg: str, hover_bg: str, normal_fg: str = None, hover_fg: str = None):
    def on_enter(_):
        try:
            widget.configure(background=hover_bg)
            if hover_fg:
                widget.configure(foreground=hover_fg)
        except tk.TclError:
            pass
    def on_leave(_):
        try:
            widget.configure(background=normal_bg)
            if normal_fg:
                widget.configure(foreground=normal_fg)
        except tk.TclError:
            pass
    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)

def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")

def liters_str(value_l: float, unit: str) -> str:
    if unit == "м³":
        return f"{value_l/1000:.3f} м³"
    return f"{value_l:.1f} л"

def ensure_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def today_str() -> str:
    return dt.date.today().isoformat()

def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)

# ------------------------------ LogManager ------------------------------

class LogManager:
    """
    Менеджер логирования действий пользователя и системных событий.
    Пишет в текстовый файл и хранит краткую историю в памяти.
    """
    def __init__(self, file_path: str = LOG_FILE):
        self.file_path = file_path
        ensure_dir(self.file_path)
        self.memory_log: List[str] = []
        self.log("Инициализация логирования")

    def log(self, message: str):
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        self.memory_log.append(line)
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # Fallback: ignore file issues to avoid crashing
            pass

    def get_recent(self, n: int = 200) -> List[str]:
        return self.memory_log[-n:]

# ------------------------------ DatabaseManager ------------------------------

class DatabaseManager:
    """
    Менеджер хранения данных. Использует SQLite.
    Таблицы:
    - entries(id, date, liters, price_per_liter, category)
    - vip_activations(id, code, date, active)
    - settings(key, value)
    - logs(id, ts, message)
    """
    def __init__(self, db_path: str = DB_FILE, logger: Optional[LogManager] = None):
        self.db_path = db_path
        self.logger = logger
        ensure_dir(self.db_path)
        self._init_db()

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            liters REAL NOT NULL,
            price_per_liter REAL NOT NULL,
            category TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vip_activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            active INTEGER NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            message TEXT NOT NULL
        )
        """)
        con.commit()
        con.close()
        if self.logger:
            self.logger.log("Инициализирована база данных")

    # Entries CRUD
    def add_entry(self, date: str, liters: float, price_per_liter: float, category: str) -> int:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("INSERT INTO entries(date, liters, price_per_liter, category) VALUES(?,?,?,?)",
                    (date, liters, price_per_liter, category))
        con.commit()
        rowid = cur.lastrowid
        con.close()
        if self.logger:
            self.logger.log(f"Добавлена запись расхода: {date}, {liters} л, {price_per_liter} руб/л, {category}")
        return rowid

    def update_entry(self, entry_id: int, date: str, liters: float, price_per_liter: float, category: str):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("UPDATE entries SET date=?, liters=?, price_per_liter=?, category=? WHERE id=?",
                    (date, liters, price_per_liter, category, entry_id))
        con.commit()
        con.close()
        if self.logger:
            self.logger.log(f"Обновлена запись id={entry_id}")

    def delete_entry(self, entry_id: int):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        con.commit()
        con.close()
        if self.logger:
            self.logger.log(f"Удалена запись id={entry_id}")

    def list_entries(self) -> List[Dict[str, Any]]:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT id, date, liters, price_per_liter, category FROM entries ORDER BY date ASC, id ASC")
        rows = cur.fetchall()
        con.close()
        data = [{"id": r[0], "date": r[1], "liters": r[2], "price_per_liter": r[3], "category": r[4]} for r in rows]
        return data

    def list_entries_period(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("""
        SELECT id, date, liters, price_per_liter, category
        FROM entries WHERE date BETWEEN ? AND ?
        ORDER BY date ASC, id ASC
        """, (start_date, end_date))
        rows = cur.fetchall()
        con.close()
        return [{"id": r[0], "date": r[1], "liters": r[2], "price_per_liter": r[3], "category": r[4]} for r in rows]

    # VIP
    def set_vip_active(self, code: str, active: bool):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("INSERT INTO vip_activations(code, date, active) VALUES(?,?,?)",
                    (code, dt.datetime.now().isoformat(), int(active)))
        con.commit()
        con.close()
        if self.logger:
            self.logger.log(f"VIP {'активирован' if active else 'деактивирован'} кодом: {code}")

    def get_last_vip_state(self) -> bool:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT active FROM vip_activations ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        con.close()
        return bool(row[0]) if row else False

    # Settings
    def save_setting(self, key: str, value: Any):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)))
        con.commit()
        con.close()
        if self.logger:
            self.logger.log(f"Сохранена настройка '{key}'")

    def load_setting(self, key: str, default: Any = None) -> Any:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        con.close()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                return default
        return default

    # Logs table (secondary persistent log)
    def persist_log(self, ts: str, message: str):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("INSERT INTO logs(ts, message) VALUES(?,?)", (ts, message))
        con.commit()
        con.close()

# ------------------------------ VIPManager ------------------------------

class VIPManager:
    """
    Менеджер VIP-доступа: проверка кода, история активаций, текущий статус.
    """
    def __init__(self, db: DatabaseManager, logger: LogManager):
        self.db = db
        self.logger = logger
        self._active = self.db.get_last_vip_state()

    def check_code(self, code: str) -> bool:
        ok = (code.strip() == VIP_CODE)
        self._active = ok
        self.db.set_vip_active(code.strip(), ok)
        self.logger.log("Проверка VIP-кода: " + ("успех" if ok else "неверно"))
        return ok

    def is_active(self) -> bool:
        return self._active

    def deactivate(self):
        self._active = False
        self.db.set_vip_active(VIP_CODE, False)
        self.logger.log("VIP временно отключён пользователем")

# ------------------------------ SettingsManager ------------------------------

class SettingsManager:
    """
    Менеджер настроек:
    - units: 'литры' или 'м³'
    - norm_daily_liters: норма расхода в литрах в день
    - notifications_enabled: включение уведомлений
    - theme_color: основной цвет интерфейса
    """
    DEFAULTS = {
        "units": "литры",
        "norm_daily_liters": 200.0,
        "notifications_enabled": True,
        "theme_color": BRAND_2
    }

    def __init__(self, db: DatabaseManager, logger: LogManager):
        self.db = db
        self.logger = logger
        self.state = {}
        for k, v in self.DEFAULTS.items():
            self.state[k] = self.db.load_setting(k, v)

    def get(self, key: str):
        return self.state.get(key, self.DEFAULTS.get(key))

    def set(self, key: str, value: Any):
        self.state[key] = value
        self.db.save_setting(key, value)
        self.logger.log(f"Настройка изменена: {key} = {value}")

# ------------------------------ StatisticsEngine ------------------------------

class StatisticsEngine:
    """
    Расчёт статистик:
    - Дневная, недельная, месячная
    - Средний расход по категориям
    - Суммарная стоимость
    - Сравнение с предыдущими периодами
    - Аномальные дни (>25% роста)
    """
    def __init__(self, db: DatabaseManager, settings: SettingsManager):
        self.db = db
        self.settings = settings

    def _period_bounds(self, mode: str) -> Tuple[str, str]:
        today = dt.date.today()
        if mode == "day":
            start = today
            end = today
        elif mode == "week":
            start = today - dt.timedelta(days=today.weekday())
            end = start + dt.timedelta(days=6)
        elif mode == "month":
            start = today.replace(day=1)
            next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            end = next_month - dt.timedelta(days=1)
        else:
            start = today
            end = today
        return start.isoformat(), end.isoformat()

    def get_stats(self, mode: str = "day") -> Dict[str, Any]:
        start, end = self._period_bounds(mode)
        entries = self.db.list_entries_period(start, end)
        total_liters = sum(e["liters"] for e in entries)
        total_cost = sum(e["liters"] * e["price_per_liter"] for e in entries)
        by_cat: Dict[str, float] = {}
        for e in entries:
            by_cat[e["category"]] = by_cat.get(e["category"], 0.0) + e["liters"]
        avg_cat = {k: v/len(entries) if entries else 0.0 for k, v in by_cat.items()}

        # previous period
        if mode == "day":
            prev_start = (parse_date(start) - dt.timedelta(days=1)).isoformat()
            prev_end = (parse_date(end) - dt.timedelta(days=1)).isoformat()
        elif mode == "week":
            prev_start = (parse_date(start) - dt.timedelta(days=7)).isoformat()
            prev_end = (parse_date(end) - dt.timedelta(days=7)).isoformat()
        else:  # month
            s = parse_date(start)
            prev_month_end = s - dt.timedelta(days=1)
            prev_month_start = prev_month_end.replace(day=1)
            prev_start, prev_end = prev_month_start.isoformat(), prev_month_end.isoformat()
        prev_entries = self.db.list_entries_period(prev_start, prev_end)
        prev_total_liters = sum(e["liters"] for e in prev_entries)

        change_pct = None
        if prev_total_liters > 0:
            change_pct = ((total_liters - prev_total_liters) / prev_total_liters) * 100.0

        # anomalies per day in current period
        anomalies: List[Dict[str, Any]] = []
        # group current by day
        day_map: Dict[str, float] = {}
        for e in entries:
            day_map[e["date"]] = day_map.get(e["date"], 0.0) + e["liters"]
        # group previous by day
        prev_day_map: Dict[str, float] = {}
        for e in prev_entries:
            prev_day_map[e["date"]] = prev_day_map.get(e["date"], 0.0) + e["liters"]
        for d, val in day_map.items():
            prev_val = prev_day_map.get((parse_date(d) - dt.timedelta(days=1)).isoformat(), 0.0)
            if prev_val > 0 and (val - prev_val)/prev_val > 0.25:
                anomalies.append({"date": d, "liters": val, "increase_pct": ((val - prev_val)/prev_val)*100})
        return {
            "mode": mode,
            "start": start,
            "end": end,
            "total_liters": total_liters,
            "total_cost": total_cost,
            "avg_by_category": avg_cat,
            "change_pct": change_pct,
            "anomalies": anomalies,
            "entries": entries,
        }

    def aggregate_by(self, period: str = "day") -> List[Tuple[str, float]]:
        """
        Возвращает [(label, liters)] за весь диапазон (исторически), агрегируя по дням/неделям/месяцам.
        """
        entries = self.db.list_entries()
        # Build map
        acc: Dict[str, float] = {}
        for e in entries:
            d = parse_date(e["date"])
            if period == "day":
                key = d.isoformat()
            elif period == "week":
                # ISO week
                key = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
            else:  # month
                key = f"{d.year}-{d.month:02d}"
            acc[key] = acc.get(key, 0.0) + e["liters"]
        return sorted(acc.items(), key=lambda x: x[0])

    def by_category(self) -> List[Tuple[str, float]]:
        entries = self.db.list_entries()
        acc: Dict[str, float] = {}
        for e in entries:
            acc[e["category"]] = acc.get(e["category"], 0.0) + e["liters"]
        return sorted(acc.items(), key=lambda x: x[0])

# ------------------------------ GraphEngine ------------------------------

class GraphEngine:
    """
    Построение графиков:
    - Линейные, столбчатые, круговые
    - Расход по дням/неделям/месяцам
    - Расход по категориям
    - Сохранение графиков в PNG
    """
    def __init__(self, stats: StatisticsEngine):
        self.stats = stats

    def _figure(self, title: str) -> Figure:
        fig = Figure(figsize=(7.0, 4.0), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_title(title)
        ax.grid(True, alpha=0.25)
        return fig

    def line_daily(self) -> Figure:
        data = self.stats.aggregate_by("day")
        labels, values = zip(*data) if data else ([], [])
        fig = self._figure("Линейный график: расход по дням")
        ax = fig.axes[0]
        ax.plot(labels, values, color=BRAND_2, marker="o")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("Литры")
        return fig

    def bar_weekly(self) -> Figure:
        data = self.stats.aggregate_by("week")
        labels, values = zip(*data) if data else ([], [])
        fig = self._figure("Столбчатый график: расход по неделям")
        ax = fig.axes[0]
        ax.bar(labels, values, color=BRAND_3)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("Литры")
        return fig

    def pie_categories(self) -> Figure:
        data = self.stats.by_category()
        labels, values = zip(*data) if data else ([], [])
        fig = Figure(figsize=(5.5, 5.5), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_title("Круговая диаграмма: расход по категориям")
        if values:
            ax.pie(values, labels=labels, autopct="%1.1f%%", colors=[BRAND_1, BRAND_2, BRAND_3, BRAND_4],
                   startangle=90, wedgeprops={"linewidth": 1, "edgecolor": "white"})
        return fig

    @staticmethod
    def save_figure(fig: Figure, path: str):
        ensure_dir(path)
        fig.savefig(path, bbox_inches="tight")

# ------------------------------ ExportEngine ------------------------------

class ExportEngine:
    """
    Экспорт данных:
    - CSV
    - Excel (pandas/openpyxl)
    - PDF отчёты (reportlab)
    Включает период и графики (PNG вставка через reportlab).
    """
    def __init__(self, db: DatabaseManager, stats: StatisticsEngine, logger: LogManager):
        self.db = db
        self.stats = stats
        self.logger = logger

    def export_csv(self, path: str, start: str, end: str):
        ensure_dir(path)
        data = self.db.list_entries_period(start, end)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "date", "liters", "price_per_liter", "category"])
            for e in data:
                w.writerow([e["id"], e["date"], e["liters"], e["price_per_liter"], e["category"]])
        self.logger.log(f"Экспорт CSV: {path} ({start}..{end})")

    def export_excel(self, path: str, start: str, end: str):
        ensure_dir(path)
        data = self.db.list_entries_period(start, end)
        df = pd.DataFrame(data)
        if not df.empty:
            df["cost"] = df["liters"] * df["price_per_liter"]
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Entries")
            # Добавим сводку
            s = self.stats.get_stats("day")  # пример, можно вывести больше
            summary = pd.DataFrame({
                "metric": ["total_liters", "total_cost"],
                "value": [s["total_liters"], s["total_cost"]]
            })
            summary.to_excel(writer, index=False, sheet_name="Summary")
        self.logger.log(f"Экспорт Excel: {path} ({start}..{end})")

    def export_pdf(self, path: str, start: str, end: str, figures: List[Tuple[str, str]]):
        """
        figures: список (title, PNG_path) для вставки в PDF.
        """
        ensure_dir(path)
        c = canvas.Canvas(path, pagesize=landscape(A4))
        w, h = landscape(A4)

        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(colors.HexColor(BRAND_4))
        c.drawString(2*cm, h - 2*cm, f"{APP_NAME} — Отчёт ({start}..{end})")

        c.setFillColor(colors.black)
        c.setFont("Helvetica", 11)
        s = self.stats.get_stats("day")
        lines = [
            f"Суммарный расход (сегодня): {s['total_liters']:.1f} л",
            f"Суммарная стоимость (сегодня): {s['total_cost']:.2f}",
            f"Аномальные дни (текущий период): {len(s['anomalies'])}"
        ]
        y = h - 3.5*cm
        for line in lines:
            c.drawString(2*cm, y, line)
            y -= 0.7*cm

        # Вставка графиков
        y_graph = y - 0.5*cm
        for title, img_path in figures:
            if os.path.exists(img_path):
                c.setFont("Helvetica-Bold", 12)
                c.drawString(2*cm, y_graph, title)
                y_graph -= 0.7*cm
                c.drawImage(img_path, 2*cm, y_graph - 8*cm, width=20*cm, height=8*cm, preserveAspectRatio=True, anchor='sw')
                y_graph -= 8.5*cm
                if y_graph < 3*cm:
                    c.showPage()
                    y_graph = h - 3*cm
        c.showPage()
        c.save()
        self.logger.log(f"Экспорт PDF: {path} ({start}..{end})")

# ------------------------------ AdviceEngine ------------------------------

class AdviceEngine:
    """
    Генерация рекомендаций и анализ утечек:
    - Советы по экономии
    - Предупреждения о возможных утечках
    - Анализ аномалий и уведомления
    """
    def __init__(self, stats: StatisticsEngine, settings: SettingsManager, logger: LogManager):
        self.stats = stats
        self.settings = settings
        self.logger = logger

    def generate_tips(self) -> List[Dict[str, Any]]:
        s_day = self.stats.get_stats("day")
        s_week = self.stats.get_stats("week")
        s_month = self.stats.get_stats("month")
        tips = []

        norm = self.settings.get("norm_daily_liters")
        # Экономия воды
        if s_day["total_liters"] > norm:
            tips.append({
                "title": "Превышение дневной нормы",
                "text": f"Сегодня расход {s_day['total_liters']:.1f} л. Попробуйте уменьшить время душа и проверить смесители."
            })
        else:
            tips.append({
                "title": "Хороший уровень расхода",
                "text": f"Сегодня расход в пределах нормы ({s_day['total_liters']:.1f} л ≤ {norm:.1f} л). Продолжайте!"
            })

        # Категория
        by_cat = self.stats.by_category()
        if by_cat:
            top_cat, top_val = max(by_cat, key=lambda x: x[1])
            tips.append({
                "title": "Основной источник расхода",
                "text": f"Больше всего воды уходит на '{top_cat}': {top_val:.1f} л. Подумайте о малорасходных режимах."
            })

        # Утечки/аномалии
        if len(s_week["anomalies"]) > 0 or len(s_month["anomalies"]) > 0:
            tips.append({
                "title": "Возможные утечки",
                "text": "Обнаружены аномальные дни. Проверьте вентили, соединения и работу стиральной машины."
            })

        # Экология
        tips.append({
            "title": "Экологические рекомендации",
            "text": "Собирайте холодную воду при ожидании горячей для полива растений. Используйте экономичные насадки."
        })
        self.logger.log("Сгенерированы советы по экономии")
        return tips

    def detect_leaks(self) -> List[Dict[str, Any]]:
        s_week = self.stats.get_stats("week")
        leaks = []
        for a in s_week["anomalies"]:
            leaks.append({"date": a["date"], "liters": a["liters"], "increase_pct": a["increase_pct"]})
        if leaks:
            self.logger.log(f"Выявлены возможные утечки: {len(leaks)} аномалий")
        return leaks

# ------------------------------ Forecasting ------------------------------

def linear_forecast(values: List[float], horizon: int = 7) -> List[float]:
    """
    Простейшая линейная экстраполяция:
    - если numpy доступен: polyfit на тренде
    - иначе: вручную по формуле линрегресс
    """
    if not values:
        return [0.0]*horizon
    x = list(range(len(values)))
    if np is not None:
        try:
            coeffs = np.polyfit(x, values, deg=1)
            a, b = coeffs[0], coeffs[1]
        except Exception:
            a, b = 0.0, values[-1]
    else:
        # manual regression
        n = len(values)
        mean_x = sum(x)/n
        mean_y = sum(values)/n
        denom = sum((xi-mean_x)**2 for xi in x) or 1e-9
        a = sum((xi-mean_x)*(yi-mean_y) for xi, yi in zip(x, values)) / denom
        b = mean_y - a*mean_x
    forecast = []
    start = len(values)
    for h in range(horizon):
        y = a*(start + h) + b
        forecast.append(max(0.0, y))
    return forecast

# ------------------------------ AquaBrizApp (UI) ------------------------------

class AquaBrizApp(tk.Tk):
    """
    Основной интерфейс приложения AquaBriz:
    - Главное окно: кнопки для всех функций, в т.ч. VIP
    - Окна: Ввод расхода, Статистика, Графики(VIP), Советы(VIP), Экспорт(VIP),
            Прогноз(VIP), Анализ утечек(VIP), Настройки(VIP), VIP-доступ, Справка
    - Анимации, hover-эффекты, аккуратная сетка, скроллы
    """
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — учёт расхода воды")
        self.geometry("1050x680")
        self.configure(bg=BG_LIGHT)
        self.minsize(980, 640)
        self.iconbitmap("") if hasattr(self, "iconbitmap") else None  # silently ignore

        # Managers
        self.logger = LogManager(LOG_FILE)
        self.db = DatabaseManager(DB_FILE, self.logger)
        self.settings = SettingsManager(self.db, self.logger)
        self.stats_engine = StatisticsEngine(self.db, self.settings)
        self.graph_engine = GraphEngine(self.stats_engine)
        self.vip_manager = VIPManager(self.db, self.logger)
        self.export_engine = ExportEngine(self.db, self.stats_engine, self.logger)
        self.advice_engine = AdviceEngine(self.stats_engine, self.settings, self.logger)

        # Styles
        self._init_styles()

        # Header
        self._build_header()
        # Main buttons
        self._build_main_menu()

        # Footer log preview
        self._build_footer()

        # Show hint about VIP if not active
        self.after(600, self._welcome_hint)

    def _init_styles(self):
        style = ttk.Style(self)
        style.theme_use("default")
        # Base
        style.configure("TFrame", background=BG_LIGHT)
        style.configure("Card.TFrame", background="white", relief="flat")
        style.configure("Title.TLabel", background=BG_LIGHT, foreground=BRAND_4, font=("Segoe UI", 16, "bold"))
        style.configure("SubTitle.TLabel", background=BG_LIGHT, foreground=BRAND_3, font=("Segoe UI", 11))
        style.configure("TLabel", background=BG_LIGHT, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        style.configure("Section.TLabelframe", background=BG_LIGHT, foreground=BRAND_3, font=("Segoe UI", 11, "bold"))
        style.configure("Section.TLabelframe.Label", background=BG_LIGHT, foreground=BRAND_3, font=("Segoe UI", 11, "bold"))
        # Buttons
        style.configure("Main.TButton", padding=12, font=("Segoe UI", 11, "bold"),
                        background=BRAND_2, foreground="white", borderwidth=0)
        style.map("Main.TButton",
                  background=[("active", BRAND_3), ("disabled", "#9fbcd6")],
                  foreground=[("disabled", "#e6eef7")])
        style.configure("VIP.TButton", padding=10, font=("Segoe UI", 10, "bold"),
                        background=BRAND_1, foreground="white", borderwidth=0)
        style.map("VIP.TButton", background=[("active", BRAND_2)])

        style.configure("Ghost.TButton", padding=8, font=("Segoe UI", 9),
                        background="#e9f4fb", foreground=BRAND_4, borderwidth=0)

        # Entries
        style.configure("TEntry", padding=6, relief="flat")
        style.configure("TCombobox", padding=6, relief="flat")
        style.configure("TLabelframe", background=BG_LIGHT)

    def _build_header(self):
        header = ttk.Frame(self, style="TFrame")
        header.pack(fill="x", padx=18, pady=(14, 8))
        title = ttk.Label(header, text=f"{APP_NAME}", style="Title.TLabel")
        subtitle = ttk.Label(header, text="Профессиональный учет расхода воды • версия " + APP_VERSION,
                             style="SubTitle.TLabel")
        title.pack(side="left")
        subtitle.pack(side="right")

    def _button(self, parent, text, cmd, vip=False):
        btn = ttk.Button(parent, text=text, command=cmd, style="Main.TButton" if not vip else "VIP.TButton")
        # hover effect via a transparent overlay button is tricky with ttk styles; instead, wrap in Frame with bg change
        # We'll use bind on the parent frame to emulate slight shadow
        frame = tk.Frame(parent, bg=BG_LIGHT)
        frame.pack_propagate(False)
        frame.configure(width=210, height=60, padx=0, pady=0)
        btn.pack(fill="both", expand=True, padx=1, pady=1)
        add_hover_effect(frame, BG_LIGHT, "#eef7ff")
        return frame, btn

    def _build_main_menu(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        grid = ttk.Frame(container)
        grid.pack(fill="both", expand=True)

        buttons = [
            ("Ввести расход", self.open_input_window, False),
            ("Статистика", self.open_stats_window, False),
            ("Графики (VIP)", self.open_graphs_window, True),
            ("Советы (VIP)", self.open_advice_window, True),
            ("Экспорт (VIP)", self.open_export_window, True),
            ("Прогноз (VIP)", self.open_forecast_window, True),
            ("Анализ утечек (VIP)", self.open_leak_window, True),
            ("Настройки (VIP)", self.open_settings_window, True),
            ("VIP-доступ", self.open_vip_window, False),
            ("Справка", self.open_help_window, False),
        ]

        for i, (text, cmd, vip) in enumerate(buttons):
            r, c = divmod(i, 2)
            holder = ttk.Frame(grid, style="TFrame")
            holder.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")
            grid.grid_rowconfigure(r, weight=1)
            grid.grid_columnconfigure(c, weight=1)
            frame, btn = self._button(holder, text, cmd, vip)
            frame.pack(fill="both", expand=True)
            # disable VIP buttons if not active
            if vip and not self.vip_manager.is_active():
                btn.state(["disabled"])

        # Decorative
        deco = ttk.Labelframe(container, text="Лента действий", style="Section.TLabelframe")
        deco.pack(fill="both", expand=True, padx=4, pady=(8, 0))
        self.log_text = tk.Text(deco, height=6, bg="white", fg=TEXT_COLOR, relief="flat")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self._refresh_footer_logs()

    def _refresh_footer_logs(self):
        self.log_text.delete("1.0", "end")
        for line in self.logger.get_recent(20):
            self.log_text.insert("end", line + "\n")

    def _build_footer(self):
        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=18, pady=8)
        info = ttk.Label(footer, text="© AquaBriz • Локальное приложение • Ваши данные хранятся у вас",
                         style="SubTitle.TLabel")
        info.pack(side="left")

        self.vip_label = ttk.Label(footer,
                                   text="VIP: активен" if self.vip_manager.is_active() else "VIP: не активен",
                                   style="SubTitle.TLabel")
        self.vip_label.pack(side="right")

    def _welcome_hint(self):
        if not self.vip_manager.is_active():
            messagebox.info = messagebox.showinfo  # alias
            messagebox.info("Доступ к VIP", "Активируйте VIP-доступ для расширенных функций: Графики, Советы, Экспорт, Прогноз, Анализ утечек, Настройки")

    # ------------------------------ Windows ------------------------------

    def _open_toplevel(self, title: str, width: int = 900, height: int = 600) -> tk.Toplevel:
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry(f"{width}x{height}+{self.winfo_rootx()+40}+{self.winfo_rooty()+40}")
        win.configure(bg=BG_LIGHT)
        win.transient(self)
        win.grab_set()
        fade_in_window(win)
        return win

    def require_vip(self) -> bool:
        if not self.vip_manager.is_active():
            messagebox.showwarning("VIP-требуется", "Эта функция доступна только при активном VIP. Откройте 'VIP-доступ'.")
            return False
        return True

    # Input window
    def open_input_window(self):
        win = self._open_toplevel("Ввод расхода")
        self.logger.log("Открыто окно: Ввод расхода")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        form = ttk.Labelframe(container, text="Новая запись", style="Section.TLabelframe")
        form.pack(fill="x", padx=6, pady=6)

        # Fields
        ttk.Label(form, text="Расход (литры):").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        liters_var = tk.StringVar(value="")
        liters_entry = ttk.Entry(form, textvariable=liters_var, width=20)
        liters_entry.grid(row=0, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(form, text="Стоимость за литр:").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        price_var = tk.StringVar(value="0.0")
        price_entry = ttk.Entry(form, textvariable=price_var, width=20)
        price_entry.grid(row=1, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(form, text="Категория:").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        category_var = tk.StringVar(value="Душ")
        category_combo = ttk.Combobox(form, textvariable=category_var, state="readonly",
                                      values=["Душ", "Кухня", "Стиральная машина", "Другое"], width=27)
        category_combo.grid(row=2, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(form, text="Дата (YYYY-MM-DD):").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        date_var = tk.StringVar(value=today_str())
        date_entry = ttk.Entry(form, textvariable=date_var, width=20)
        date_entry.grid(row=3, column=1, sticky="w", padx=6, pady=6)

        def add_record():
            liters = safe_float(liters_var.get())
            price = safe_float(price_var.get())
            date_s = date_var.get().strip()
            cat = category_var.get().strip()
            # Validation
            if liters is None or price is None or not date_s or not cat:
                messagebox.showerror("Ошибка ввода", "Проверьте поля: расход, стоимость, категория, дата.")
                return
            if liters < 0 or price < 0:
                messagebox.showerror("Ошибка ввода", "Значения не должны быть отрицательными.")
                return
            try:
                _ = parse_date(date_s)
            except Exception:
                messagebox.showerror("Ошибка ввода", "Дата должна быть в формате YYYY-MM-DD.")
                return

            self.db.add_entry(date_s, liters, price, cat)
            self.logger.log("Пользователь добавил запись расхода")
            refresh_list()
            liters_var.set("")
            price_var.set("0.0")
            category_var.set("Душ")
            date_var.set(today_str())
            self._refresh_footer_logs()

        add_btn = ttk.Button(form, text="Добавить", style="Main.TButton", command=add_record)
        add_btn.grid(row=4, column=0, columnspan=2, sticky="we", padx=6, pady=6)

        # Records
        records_frame = ttk.Labelframe(container, text="Записи", style="Section.TLabelframe")
        records_frame.pack(fill="both", expand=True, padx=6, pady=6)

        columns = ("id", "date", "liters", "price", "category", "cost")
        tree = ttk.Treeview(records_frame, columns=columns, show="headings", height=12)
        for col in columns:
            tree.heading(col, text=col.upper())
            tree.column(col, width=120, anchor="center")
        tree.column("id", width=60)
        tree.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        scrollbar = ttk.Scrollbar(records_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        def refresh_list():
            for i in tree.get_children():
                tree.delete(i)
            for e in self.db.list_entries():
                cost = e["liters"] * e["price_per_liter"]
                tree.insert("", "end", values=(e["id"], e["date"], f"{e['liters']:.1f}",
                                               f"{e['price_per_liter']:.4f}", e["category"], f"{cost:.2f}"))

        refresh_list()

        # Edit/Delete
        editor = ttk.Labelframe(container, text="Редактирование", style="Section.TLabelframe")
        editor.pack(fill="x", padx=6, pady=6)
        eid_var, edate_var, eliters_var, eprice_var, ecat_var = (tk.StringVar(), tk.StringVar(), tk.StringVar(),
                                                                 tk.StringVar(), tk.StringVar())
        ttk.Label(editor, text="ID:").grid(row=0, column=0, padx=6, pady=6)
        ttk.Entry(editor, textvariable=eid_var, width=10, state="readonly").grid(row=0, column=1, padx=6, pady=6)
        ttk.Label(editor, text="Дата:").grid(row=0, column=2, padx=6, pady=6)
        ttk.Entry(editor, textvariable=edate_var, width=18).grid(row=0, column=3, padx=6, pady=6)
        ttk.Label(editor, text="Литры:").grid(row=1, column=0, padx=6, pady=6)
        ttk.Entry(editor, textvariable=eliters_var, width=18).grid(row=1, column=1, padx=6, pady=6)
        ttk.Label(editor, text="Цена/л:").grid(row=1, column=2, padx=6, pady=6)
        ttk.Entry(editor, textvariable=eprice_var, width=18).grid(row=1, column=3, padx=6, pady=6)
        ttk.Label(editor, text="Категория:").grid(row=2, column=0, padx=6, pady=6)
        ttk.Combobox(editor, textvariable=ecat_var, state="readonly",
                     values=["Душ", "Кухня", "Стиральная машина", "Другое"], width=20).grid(row=2, column=1, padx=6, pady=6)

        def on_select(_):
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            eid_var.set(vals[0])
            edate_var.set(vals[1])
            eliters_var.set(vals[2])
            eprice_var.set(vals[3])
            ecat_var.set(vals[4])

        tree.bind("<<TreeviewSelect>>", on_select)

        def save_edit():
            if not eid_var.get():
                return
            liters = safe_float(eliters_var.get())
            price = safe_float(eprice_var.get())
            date_s = edate_var.get().strip()
            cat = ecat_var.get().strip()
            if liters is None or price is None or not date_s or not cat:
                messagebox.showerror("Ошибка ввода", "Проверьте поля перед сохранением.")
                return
            try:
                parse_date(date_s)
            except Exception:
                messagebox.showerror("Ошибка ввода", "Дата должна быть в формате YYYY-MM-DD.")
                return
            self.db.update_entry(int(eid_var.get()), date_s, liters, price, cat)
            self.logger.log(f"Изменена запись id={eid_var.get()}")
            refresh_list()
            self._refresh_footer_logs()

        def delete_sel():
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0], "values")
            eid = int(vals[0])
            if messagebox.askyesno("Удаление", f"Удалить запись id={eid}?"):
                self.db.delete_entry(eid)
                self.logger.log(f"Удалена запись id={eid}")
                refresh_list()
                self._refresh_footer_logs()

        ttk.Button(editor, text="Сохранить изменения", style="Ghost.TButton", command=save_edit).grid(row=3, column=0, padx=6, pady=6)
        ttk.Button(editor, text="Удалить", style="Ghost.TButton", command=delete_sel).grid(row=3, column=1, padx=6, pady=6)

    # Statistics
    def open_stats_window(self):
        win = self._open_toplevel("Статистика")
        self.logger.log("Открыто окно: Статистика")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        mode_var = tk.StringVar(value="day")
        ttk.Label(container, text="Период:").pack(anchor="w")
        ttk.Radiobutton(container, text="День", variable=mode_var, value="day").pack(anchor="w")
        ttk.Radiobutton(container, text="Неделя", variable=mode_var, value="week").pack(anchor="w")
        ttk.Radiobutton(container, text="Месяц", variable=mode_var, value="month").pack(anchor="w")

        card = tk.Frame(container, bg="white", bd=0, highlightthickness=1, highlightbackground="#dce7f3")
        card.pack(fill="both", expand=True, padx=4, pady=8)

        txt = tk.Text(card, bg="white", fg=TEXT_COLOR, relief="flat", wrap="word")
        txt.pack(fill="both", expand=True, padx=8, pady=8)

        def refresh():
            s = self.stats_engine.get_stats(mode_var.get())
            txt.delete("1.0", "end")
            txt.insert("end", f"Период: {s['start']} .. {s['end']}\n")
            txt.insert("end", f"Суммарный расход: {liters_str(s['total_liters'], self.settings.get('units'))}\n")
            txt.insert("end", f"Суммарная стоимость: {money(s['total_cost'])}\n")
            if s["change_pct"] is not None:
                txt.insert("end", f"Изменение к предыдущему периоду: {s['change_pct']:.1f}%\n")
            txt.insert("end", "\nСредний расход по категориям:\n")
            for k, v in s["avg_by_category"].items():
                txt.insert("end", f" • {k}: {v:.1f} л\n")
            if s["anomalies"]:
                txt.insert("end", "\nАномальные дни (>25% роста):\n")
                for a in s["anomalies"]:
                    txt.insert("end", f" • {a['date']}: +{a['increase_pct']:.1f}% ({a['liters']:.1f} л)\n")
            else:
                txt.insert("end", "\nАномальных дней не обнаружено.\n")

        ttk.Button(container, text="Обновить", style="Ghost.TButton", command=refresh).pack(anchor="w", pady=4)
        refresh()

    # Graphs (VIP)
    def open_graphs_window(self):
        if not self.require_vip():
            return
        win = self._open_toplevel("Графики (VIP)")
        self.logger.log("Открыто окно: Графики")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        tabs = ttk.Notebook(container)
        tabs.pack(fill="both", expand=True)

        # Line daily
        f1 = ttk.Frame(tabs)
        tabs.add(f1, text="Линия: дни")
        fig1 = self.graph_engine.line_daily()
        canvas1 = FigureCanvasTkAgg(fig1, master=f1)
        canvas1.draw()
        canvas1.get_tk_widget().pack(fill="both", expand=True)

        # Bar weekly
        f2 = ttk.Frame(tabs)
        tabs.add(f2, text="Столбцы: недели")
        fig2 = self.graph_engine.bar_weekly()
        canvas2 = FigureCanvasTkAgg(fig2, master=f2)
        canvas2.draw()
        canvas2.get_tk_widget().pack(fill="both", expand=True)

        # Pie categories
        f3 = ttk.Frame(tabs)
        tabs.add(f3, text="Круг: категории")
        fig3 = self.graph_engine.pie_categories()
        canvas3 = FigureCanvasTkAgg(fig3, master=f3)
        canvas3.draw()
        canvas3.get_tk_widget().pack(fill="both", expand=True)

        def save_figures():
            base = filedialog.askdirectory(title="Выберите папку для сохранения графиков")
            if not base:
                return
            p1 = os.path.join(base, "daily_line.png")
            p2 = os.path.join(base, "weekly_bar.png")
            p3 = os.path.join(base, "categories_pie.png")
            GraphEngine.save_figure(fig1, p1)
            GraphEngine.save_figure(fig2, p2)
            GraphEngine.save_figure(fig3, p3)
            self.logger.log(f"Сохранены графики PNG: {base}")
            messagebox.showinfo("Сохранено", "Графики сохранены в выбраной папке.")

        ttk.Button(container, text="Сохранить PNG", style="VIP.TButton", command=save_figures).pack(anchor="e", pady=8)

    # Advice (VIP)
    def open_advice_window(self):
        if not self.require_vip():
            return
        win = self._open_toplevel("Советы (VIP)")
        self.logger.log("Открыто окно: Советы")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        canvas_scroll = tk.Canvas(container, bg=BG_LIGHT, highlightthickness=0)
        scr = ttk.Scrollbar(container, orient="vertical", command=canvas_scroll.yview)
        frame = ttk.Frame(canvas_scroll)
        frame_id = canvas_scroll.create_window((0, 0), window=frame, anchor="nw")
        canvas_scroll.configure(yscrollcommand=scr.set)
        canvas_scroll.pack(side="left", fill="both", expand=True)
        scr.pack(side="right", fill="y")

        def on_config(_):
            canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
            canvas_scroll.itemconfig(frame_id, width=canvas_scroll.winfo_width())
        frame.bind("<Configure>", on_config)

        def build_cards():
            for w in frame.winfo_children():
                w.destroy()
            tips = self.advice_engine.generate_tips()
            for i, tip in enumerate(tips):
                card = tk.Frame(frame, bg="white", bd=0, highlightthickness=1, highlightbackground="#dce7f3")
                card.pack(fill="x", padx=8, pady=6)
                add_hover_effect(card, "white", "#f5fbff")
                title = tk.Label(card, text=tip["title"], bg="white", fg=BRAND_3, font=("Segoe UI", 12, "bold"))
                body = tk.Label(card, text=tip["text"], bg="white", fg=TEXT_COLOR, font=("Segoe UI", 10), wraplength=780, justify="left")
                title.pack(anchor="w", padx=10, pady=(8, 3))
                body.pack(anchor="w", padx=10, pady=(0, 10))
        build_cards()

        ttk.Button(container, text="Обновить советы", style="VIP.TButton", command=build_cards).pack(anchor="e", pady=8)

    # Forecast (VIP)
    def open_forecast_window(self):
        if not self.require_vip():
            return
        win = self._open_toplevel("Прогноз расхода (VIP)")
        self.logger.log("Открыто окно: Прогноз")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        ttk.Label(container, text="Горизонт прогноза:").pack(anchor="w")
        horizon_var = tk.IntVar(value=7)
        ttk.Spinbox(container, from_=3, to=60, textvariable=horizon_var, width=8).pack(anchor="w")

        # build values by last days
        data = self.stats_engine.aggregate_by("day")
        values = [v for _, v in data]
        forecast = linear_forecast(values, horizon_var.get())

        fig = Figure(figsize=(7.0, 4.0), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_title("Прогноз на период")
        if values:
            ax.plot(range(len(values)), values, label="История", color=BRAND_3)
        ax.plot(range(len(values), len(values)+len(forecast)), forecast, label="Прогноз", color=BRAND_1, marker="o")
        ax.legend()
        ax.grid(True, alpha=0.25)
        canvas_plot = FigureCanvasTkAgg(fig, master=container)
        canvas_plot.draw()
        canvas_plot.get_tk_widget().pack(fill="both", expand=True, pady=6)

        warn_label = ttk.Label(container, text="", style="TLabel")
        warn_label.pack(anchor="w")

        def recompute():
            nonlocal forecast
            forecast = linear_forecast(values, horizon_var.get())
            ax.clear()
            ax.set_title("Прогноз на период")
            if values:
                ax.plot(range(len(values)), values, label="История", color=BRAND_3)
            ax.plot(range(len(values), len(values)+len(forecast)), forecast, label="Прогноз", color=BRAND_1, marker="o")
            ax.legend()
            ax.grid(True, alpha=0.25)
            canvas_plot.draw()

            # предупреждение о превышении нормы
            norm = self.settings.get("norm_daily_liters")
            over_days = sum(1 for y in forecast if y > norm)
            if over_days > 0:
                warn_label.configure(text=f"Внимание: ожидается превышение дневной нормы в {over_days} дн.")
            else:
                warn_label.configure(text="Прогноз в пределах нормы.")

        ttk.Button(container, text="Пересчитать", style="VIP.TButton", command=recompute).pack(anchor="e", pady=8)
        recompute()

    # Leak analysis (VIP)
    def open_leak_window(self):
        if not self.require_vip():
            return
        win = self._open_toplevel("Анализ утечек (VIP)")
        self.logger.log("Открыто окно: Анализ утечек")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        tree = ttk.Treeview(container, columns=("date", "liters", "increase"), show="headings", height=14)
        for c in ("date", "liters", "increase"):
            tree.heading(c, text=c.upper())
            tree.column(c, width=180, anchor="center")
        tree.pack(fill="both", expand=True, padx=6, pady=6)

        def refresh():
            for i in tree.get_children():
                tree.delete(i)
            leaks = self.advice_engine.detect_leaks()
            for l in leaks:
                iid = tree.insert("", "end", values=(l["date"], f"{l['liters']:.1f}", f"+{l['increase_pct']:.1f}%"))
                # highlight
                tree.tag_configure("red", foreground="red")
                tree.item(iid, tags=("red",))
            if leaks and self.settings.get("notifications_enabled"):
                messagebox.showwarning("Обнаружены утечки", "Внимание: найдены аномальные дни. Проверьте систему.")

        ttk.Button(container, text="Обновить", style="VIP.TButton", command=refresh).pack(anchor="e", pady=8)
        refresh()

    # Settings (VIP)
    def open_settings_window(self):
        if not self.require_vip():
            return
        win = self._open_toplevel("Настройки (VIP)")
        self.logger.log("Открыто окно: Настройки")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        units_var = tk.StringVar(value=self.settings.get("units"))
        ttk.Label(container, text="Единицы измерения:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Combobox(container, textvariable=units_var, values=["литры", "м³"], state="readonly", width=15).grid(row=0, column=1, sticky="w", padx=6, pady=6)

        norm_var = tk.StringVar(value=str(self.settings.get("norm_daily_liters")))
        ttk.Label(container, text="Норма расхода (л/день):").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(container, textvariable=norm_var, width=15).grid(row=1, column=1, sticky="w", padx=6, pady=6)

        notif_var = tk.BooleanVar(value=bool(self.settings.get("notifications_enabled")))
        ttk.Label(container, text="Уведомления:").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Checkbutton(container, variable=notif_var).grid(row=2, column=1, sticky="w", padx=6, pady=6)

        theme_var = tk.StringVar(value=self.settings.get("theme_color"))
        ttk.Label(container, text="Цвет интерфейса:").grid(row=3, column=0, sticky="w", padx=6, pady=6)
        ttk.Combobox(container, textvariable=theme_var, values=[BRAND_1, BRAND_2, BRAND_3, BRAND_4], state="readonly", width=15).grid(row=3, column=1, sticky="w", padx=6, pady=6)

        def save_settings():
            # validate
            units = units_var.get()
            try:
                norm = float(norm_var.get().replace(",", "."))
            except Exception:
                messagebox.showerror("Ошибка", "Норма должна быть числом.")
                return
            self.settings.set("units", units)
            self.settings.set("norm_daily_liters", norm)
            self.settings.set("notifications_enabled", bool(notif_var.get()))
            self.settings.set("theme_color", theme_var.get())
            self._refresh_footer_logs()
            messagebox.showinfo("Сохранено", "Настройки сохранены.")
        ttk.Button(container, text="Сохранить", style="VIP.TButton", command=save_settings).grid(row=4, column=0, columnspan=2, sticky="we", padx=6, pady=12)

    # Export (VIP)
    def open_export_window(self):
        if not self.require_vip():
            return
        win = self._open_toplevel("Экспорт (VIP)")
        self.logger.log("Открыто окно: Экспорт")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        ttk.Label(container, text="Период экспорта:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        start_var = tk.StringVar(value=(dt.date.today() - dt.timedelta(days=30)).isoformat())
        end_var = tk.StringVar(value=today_str())
        ttk.Entry(container, textvariable=start_var, width=15).grid(row=0, column=1, sticky="w", padx=6, pady=6)
        ttk.Entry(container, textvariable=end_var, width=15).grid(row=0, column=2, sticky="w", padx=6, pady=6)

        def export_csv():
            path = filedialog.asksaveasfilename(title="CSV файл", defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")], initialfile="AquaBriz_export.csv")
            if not path:
                return
            self.export_engine.export_csv(path, start_var.get(), end_var.get())
            self._refresh_footer_logs()
            messagebox.showinfo("Готово", "CSV экспортирован.")

        def export_excel():
            path = filedialog.asksaveasfilename(title="Excel файл", defaultextension=".xlsx",
                                                filetypes=[("Excel", "*.xlsx")], initialfile="AquaBriz_export.xlsx")
            if not path:
                return
            try:
                self.export_engine.export_excel(path, start_var.get(), end_var.get())
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось экспортировать Excel: {e}")
                return
            self._refresh_footer_logs()
            messagebox.showinfo("Готово", "Excel экспортирован.")

        def export_pdf():
            path = filedialog.asksaveasfilename(title="PDF файл", defaultextension=".pdf",
                                                filetypes=[("PDF", "*.pdf")], initialfile="AquaBriz_report.pdf")
            if not path:
                return
            # Prepare graphs temp
            temp_dir = os.path.join(os.getcwd(), "aquabriz_tmp")
            os.makedirs(temp_dir, exist_ok=True)
            figs = []
            fig1 = self.graph_engine.line_daily()
            p1 = os.path.join(temp_dir, "daily.png")
            GraphEngine.save_figure(fig1, p1)
            figs.append(("Линия: дни", p1))

            fig2 = self.graph_engine.bar_weekly()
            p2 = os.path.join(temp_dir, "weekly.png")
            GraphEngine.save_figure(fig2, p2)
            figs.append(("Столбцы: недели", p2))

            fig3 = self.graph_engine.pie_categories()
            p3 = os.path.join(temp_dir, "categories.png")
            GraphEngine.save_figure(fig3, p3)
            figs.append(("Круг: категории", p3))

            try:
                self.export_engine.export_pdf(path, start_var.get(), end_var.get(), figs)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось экспортировать PDF: {e}")
                return
            self._refresh_footer_logs()
            messagebox.showinfo("Готово", "PDF отчёт экспортирован.")

        ttk.Button(container, text="Экспорт CSV", style="VIP.TButton", command=export_csv).grid(row=1, column=0, padx=6, pady=8, sticky="we")
        ttk.Button(container, text="Экспорт Excel", style="VIP.TButton", command=export_excel).grid(row=1, column=1, padx=6, pady=8, sticky="we")
        ttk.Button(container, text="Экспорт PDF", style="VIP.TButton", command=export_pdf).grid(row=1, column=2, padx=6, pady=8, sticky="we")

    # VIP
    def open_vip_window(self):
        win = self._open_toplevel("VIP-доступ")
        self.logger.log("Открыто окно: VIP-доступ")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        ttk.Label(container, text="Введите VIP-код:").pack(anchor="w")
        code_var = tk.StringVar()
        ttk.Entry(container, textvariable=code_var, width=20).pack(anchor="w", pady=4)

        def check():
            ok = self.vip_manager.check_code(code_var.get())
            self.vip_label.configure(text="VIP: активен" if ok else "VIP: не активен")
            # refresh main buttons state
            self._rebuild_main_buttons()
            self._refresh_footer_logs()
            messagebox.showinfo("Статус", "VIP активирован!" if ok else "Неверный код.")
        ttk.Button(container, text="Активировать", style="Main.TButton", command=check).pack(anchor="w", pady=6)

        def deactivate():
            self.vip_manager.deactivate()
            self.vip_label.configure(text="VIP: не активен")
            self._rebuild_main_buttons()
            self._refresh_footer_logs()
            messagebox.showinfo("Статус", "VIP отключён.")
        ttk.Button(container, text="Отключить VIP", style="Ghost.TButton", command=deactivate).pack(anchor="w", pady=6)

        # History
        hist = tk.Text(container, height=8, bg="white", fg=TEXT_COLOR, relief="flat")
        hist.pack(fill="both", expand=True, pady=8)
        hist.insert("end", "История активаций смотрите в логах (внизу главного окна).")

    def _rebuild_main_buttons(self):
        # Recreate main menu to update button states
        for child in self.winfo_children():
            # Keep header and footer; rebuild center area only
            pass
        # Simple approach: destroy and rebuild central area except header/footer
        # We'll destroy everything and rebuild (safe in this scenario).
        for w in list(self.winfo_children())[2:-1]:  # header (0), menu (1..?), footer (last)
            try:
                w.destroy()
            except Exception:
                pass
        self._build_main_menu()

    # Help
    def open_help_window(self):
        win = self._open_toplevel("Справка")
        self.logger.log("Открыто окно: Справка")

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=18, pady=12)

        canvas_scroll = tk.Canvas(container, bg=BG_LIGHT, highlightthickness=0)
        scr = ttk.Scrollbar(container, orient="vertical", command=canvas_scroll.yview)
        frame = ttk.Frame(canvas_scroll)
        frame_id = canvas_scroll.create_window((0, 0), window=frame, anchor="nw")
        canvas_scroll.configure(yscrollcommand=scr.set)
        canvas_scroll.pack(side="left", fill="both", expand=True)
        scr.pack(side="right", fill="y")

        def on_config(_):
            canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
            canvas_scroll.itemconfig(frame_id, width=canvas_scroll.winfo_width())
        frame.bind("<Configure>", on_config)

        blocks = [
            ("Ввод расхода", "Откройте 'Ввести расход', заполните поля: литры, стоимость за литр, категорию, дату. Нажмите 'Добавить'. Записи можно редактировать и удалять в списке ниже."),
            ("Активация VIP", "Откройте 'VIP-доступ' и введите код, который вы получили на электронную почту после покупки подписки на сайте. После успешной активации станут доступны функции: Графики, Советы, Экспорт, Прогноз, Анализ утечек, Настройки."),
            ("Статистика", "Окно 'Статистика' показывает дневную, недельную и месячную сводку: суммы, средние по категориям, сравнение с предыдущим периодом и аномальные дни."),
            ("Графики (VIP)", "В 'Графики' доступны линейные, столбчатые и круговые диаграммы с возможностью сохранить в PNG."),
            ("Советы (VIP)", "Генерируются рекомендации по экономии воды и предупреждения о возможных утечках с красивыми карточками."),
            ("Прогноз (VIP)", "Линейная экстраполяция на заданный горизонт. Показывает возможное превышение нормы."),
            ("Анализ утечек (VIP)", "Выявляет аномальные дни (>25% роста) и подсвечивает проблемные даты, показывает уведомления."),
            ("Настройки (VIP)", "Смена единиц (литры/м³), настройка нормы, уведомлений и цвета интерфейса."),
            ("Экспорт (VIP)", "Экспорт в CSV, Excel и PDF с графиками и статистикой. Выберите период и путь сохранения."),
            ("Логи действий", "В нижней части главного окна — лента действий. Все действия логируются.")
        ]

        for title, text in blocks:
            card = tk.Frame(frame, bg="white", bd=0, highlightthickness=1, highlightbackground="#dce7f3")
            card.pack(fill="x", padx=8, pady=6)
            add_hover_effect(card, "white", "#f5fbff")
            tk.Label(card, text=title, bg="white", fg=BRAND_3, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=10, pady=(8, 3))
            tk.Label(card, text=text, bg="white", fg=TEXT_COLOR, font=("Segoe UI", 10), wraplength=780, justify="left").pack(anchor="w", padx=10, pady=(0, 10))

# ------------------------------ Main ------------------------------

def main():
    app = AquaBrizApp()
    # Persist memory log entries into DB log table once per run
    for line in app.logger.get_recent(100):
        try:
            ts, msg = line[1:20], line[22:]
            app.db.persist_log(ts, msg)
        except Exception:
            pass
    app.mainloop()

if __name__ == "__main__":
    main()
