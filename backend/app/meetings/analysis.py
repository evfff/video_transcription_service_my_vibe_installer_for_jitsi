"""
Meeting Analysis Service
Отвечает за LLM-анализ транскрипта встречи:
- summary
- key_points
- decisions
- open_questions
- tasks (с приоритетами, assignee, таймкодами)
- notes_markdown

Использует LM Studio (OpenAI-compatible) через httpx.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from .config import MeetingsConfig
from .models import (
    AnalysisResult,
    AnalysisTask,
    TranscriptResult,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

# Максимальный размер одного LLM-чанка (символов)
# ~6000 символов ≈ 1500 токенов транскрипта + ~400 токенов промпта = ~2000 вход.
# При max_tokens=1500 итого ~3500 токенов — безопасно для модели с 8K контекстом.
MAX_CHUNK_CHARS = 6000
# Временная нарезка: каждый чанк покрывает не более N минут записи
CHUNK_MINUTES = 20
# Если транскрипт длиннее — делим на чанки и мёржим результаты
CHUNK_OVERLAP_LINES = 5
# Retry настройки для LLM вызовов
LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_DELAY = 2.0  # секунды (удваивается при каждой попытке)


class MeetingAnalysisService:
    """
    LLM-анализ встречи. Получает структурированный JSON-результат.
    При ошибке LLM возвращает частичный результат (graceful fallback).
    """

    def __init__(self, config: MeetingsConfig) -> None:
        self.config = config

    def analyze(
        self,
        meeting_id: str,
        title: str,
        transcript: TranscriptResult,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> AnalysisResult:
        """
        Запустить LLM-анализ транскрипта.
        Возвращает AnalysisResult (может быть частичным при ошибке LLM).
        """
        logger.info(f"[ANALYSIS] Начало анализа встречи: {title}")

        # Форматируем транскрипт и определяем нужны ли чанки
        lines = self._format_lines(transcript)
        full_text = "\n".join(lines)

        try:
            if len(full_text) <= MAX_CHUNK_CHARS:
                # Короткий митинг — один запрос
                logger.info(f"[ANALYSIS] Одиночный LLM-запрос ({len(full_text)} символов)")
                if progress_cb:
                    progress_cb(0, 1)
                prompt = self._build_prompt(title, full_text, transcript.language)
                raw_json = self._call_llm(prompt)
                result = self._parse_response(raw_json, meeting_id, title, transcript)
                if progress_cb:
                    progress_cb(1, 1)
            else:
                # Длинный митинг — разбиваем на чанки и мёржим
                result = self._analyze_chunked(meeting_id, title, transcript, lines, progress_cb)
        except Exception as exc:
            logger.error(f"[ANALYSIS] Ошибка LLM анализа: {exc}")
            result = AnalysisResult(
                meeting_id=meeting_id,
                title=title,
                language=transcript.language,
                duration_sec=transcript.audio_duration_sec,
                summary=f"[Анализ недоступен: {exc}]",
                transcript_segments=transcript.segments,
            )

        # Всегда добавляем транскрипт в результат
        result.transcript_segments = transcript.segments
        result.duration_sec = transcript.audio_duration_sec
        result.language = transcript.language

        logger.info(
            f"[ANALYSIS] ✓ Анализ завершён: "
            f"{len(result.tasks)} задач, "
            f"{len(result.key_points)} тезисов"
        )
        return result

    def save_analysis(
        self,
        result: AnalysisResult,
        artifacts_dir: Path,
    ) -> dict:
        """
        Сохранить результаты анализа:
        - analysis.json  (полный JSON)
        - summary.md     (читаемый markdown)
        - tasks.json     (только задачи)
        """
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # analysis.json
        analysis_path = artifacts_dir / "analysis.json"
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

        # summary.md
        summary_path = artifacts_dir / "summary.md"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(self._build_summary_md(result))

        # tasks.json
        tasks_path = artifacts_dir / "tasks.json"
        with open(tasks_path, "w", encoding="utf-8") as f:
            tasks_data = [t.model_dump() for t in result.tasks]
            json.dump(tasks_data, f, ensure_ascii=False, indent=2)

        logger.info("[ANALYSIS] ✓ Сохранено: analysis.json + summary.md + tasks.json")
        return {
            "analysis_json": str(analysis_path),
            "summary_md": str(summary_path),
            "tasks_json": str(tasks_path),
        }

    # ─── LLM call ─────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Вызов LM Studio API с retry (экспоненциальный backoff)."""
        payload: Dict[str, Any] = {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": self.config.llm_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.llm_max_tokens,
        }
        if self.config.llm_model:
            payload["model"] = self.config.llm_model

        last_exc: Optional[Exception] = None
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                logger.info(f"[ANALYSIS] LLM запрос → {self.config.llm_url} (попытка {attempt}/{LLM_MAX_RETRIES})")
                with httpx.Client(timeout=600.0) as client:
                    resp = client.post(self.config.llm_url, json=payload)
                    resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content
            except Exception as exc:
                last_exc = exc
                if attempt < LLM_MAX_RETRIES:
                    delay = LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(f"[ANALYSIS] LLM ошибка (попытка {attempt}): {exc} — повтор через {delay:.1f}с")
                    time.sleep(delay)
        raise RuntimeError(f"LLM недоступен после {LLM_MAX_RETRIES} попыток: {last_exc}")

    # ─── Prompt builder ───────────────────────────────────────────────────────

    def _build_prompt(
        self, title: str, transcript_text: str, language: str,
        chunk_info: str = "",
    ) -> str:
        chunk_note = f"\n[ЧАСТЬ МИТИНГА: {chunk_info}]" if chunk_info else ""
        return f"""Ты профессиональный аналитик встреч. Твоя задача — извлечь структурированную информацию из транскрипта.{chunk_note}

Встреча: "{title}"
Язык: {language}

ТРАНСКРИПТ:
{transcript_text}

ИЗВЛЕКИ и верни СТРОГО JSON (без markdown, без комментариев):
{{
  "title": "Название встречи: 2-5 слов на русском, суть темы",
  "summary": "3-5 предложений: о чём была встреча, что обсуждалось, каков итог",
  "participants": ["Имя1", "Имя2"],
  "key_points": [
    "Главный тезис или факт — конкретный, не общий"
  ],
  "decisions": [
    "Конкретное решение, принятое на встрече — то что уже решено, не задача"
  ],
  "open_questions": [
    "Вопрос или тема, которая осталась без ответа или требует дальнейшего обсуждения"
  ],
  "tasks": [
    {{
      "title": "Высокоуровневое название задачи (глагол + объект, не детализированно)",
      "description": "Контекст: зачем нужно, что конкретно сделать, ожидаемый результат",
      "assignee": "Имя ответственного если явно назван, иначе null",
      "due_date": "YYYY-MM-DD если срок явно назван, иначе null",
      "priority": "high если срочно/критично/блокер, medium если запланировано, low если пожелание",
      "source_fragment": "Точная цитата из транскрипта, доказывающая что задача была явно озвучена",
      "speaker": "SPEAKER_XX или имя спикера если известен, иначе null",
      "timecode": "HH:MM:SS откуда взята задача"
    }}
  ],
  "notes_markdown": "## Контекст и предыстория\\n<фон и причины обсуждений>\\n\\n## Ключевые обсуждения\\n<что именно обсуждалось, позиции сторон>\\n\\n## Риски и опасения\\n<если упоминались проблемы, риски, блокеры>\\n\\n## Договорённости\\n<неформальные договорённости не попавшие в решения и задачи>\\n\\n## Прочее\\n<любые важные детали, числа, имена, ссылки которые стоит сохранить>"
}}

СТРОГИЕ правила задач (ОБЯЗАТЕЛЬНО соблюдать):
1. ВКЛЮЧАЙ задачу ТОЛЬКО если она была ЯВНО ПРОГОВОРЕНА — кто-то сказал «я сделаю X», «нужно сделать X», «возьми X на себя», «давай ты займёшься X»
2. НЕ выводи задачи из контекста обсуждения — если тему обсудили, но конкретного поручения не было, это НЕ задача
3. ОБЪЕДИНЯЙ мелкие шаги одной темы в ОДНУ высокоуровневую задачу (например, «Описать архитектуру системы» вместо 3 отдельных пунктов)
4. Максимум 10-12 задач на всю встречу — только самые важные и явно назначенные
5. Приоритет high: есть дедлайн, блокирует других, назван как срочный
6. Если одна задача упомянута несколько раз — одна запись с лучшим контекстом

СТРОГИЕ правила notes_markdown:
- Сохраняй структуру разделов как показано выше (## Контекст, ## Ключевые обсуждения, ## Риски, ## Договорённости, ## Прочее)
- Пропускай раздел если он пустой (ничего не упоминалось)
- Включай конкретные цифры, сроки, имена систем, технические детали
- Это место для всего что не поместилось в summary / decisions / tasks

ОТВЕТ: ТОЛЬКО JSON, без markdown-блоков, без пояснений."""

    # ─── Response parsing ─────────────────────────────────────────────────────

    def _parse_response(
        self,
        raw_json: str,
        meeting_id: str,
        title: str,
        transcript: TranscriptResult,
    ) -> AnalysisResult:
        """Парсинг JSON ответа LLM с fallback на частичный результат"""
        # LLM иногда оборачивает JSON в ```json ... ```
        clean = re.sub(r"^```(?:json)?\s*", "", raw_json.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

        try:
            data = json.loads(clean)
        except json.JSONDecodeError as exc:
            logger.warning(f"[ANALYSIS] JSON парсинг не удался: {exc}. Пробуем извлечь...")
            # Пытаемся найти JSON в тексте
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"Не удалось распарсить JSON ответ LLM: {raw_json[:200]}")

        # Парсинг задач
        tasks = []
        for t in data.get("tasks", []):
            tasks.append(
                AnalysisTask(
                    title=t.get("title", ""),
                    description=t.get("description", ""),
                    assignee=t.get("assignee"),
                    due_date=t.get("due_date"),
                    priority=t.get("priority", "medium"),
                    source_fragment=t.get("source_fragment"),
                    speaker=t.get("speaker"),
                    timecode=t.get("timecode"),
                )
            )

        return AnalysisResult(
            meeting_id=meeting_id,
            title=data.get("title", "").strip() or title,
            summary=data.get("summary", "") or "",
            key_points=[x for x in data.get("key_points", []) if isinstance(x, str)],
            decisions=[x for x in data.get("decisions", []) if isinstance(x, str)],
            open_questions=[x for x in data.get("open_questions", []) if isinstance(x, str)],
            tasks=tasks,
            notes_markdown=data.get("notes_markdown", "") or "",
        )

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _split_by_time(self, transcript: TranscriptResult, lines: List[str]) -> List[List[str]]:
        """Нарезка транскрипта на временные блоки по CHUNK_MINUTES минут.
        
        Сохраняет CHUNK_OVERLAP_LINES строк из конца предыдущего чанка в начале следующего.
        Возвращает пустой список если сегменты недоступны.
        """
        if not transcript.segments or len(transcript.segments) != len(lines):
            return []

        chunk_secs = CHUNK_MINUTES * 60
        chunks: List[List[str]] = []
        current: List[str] = []
        chunk_start_sec = transcript.segments[0].start if transcript.segments else 0.0

        for seg, line in zip(transcript.segments, lines):
            if seg.start - chunk_start_sec >= chunk_secs and current:
                chunks.append(current)
                overlap = current[-CHUNK_OVERLAP_LINES:]
                current = list(overlap)
                chunk_start_sec = seg.start
            current.append(line)

        if current:
            chunks.append(current)
        return chunks

    def _split_by_chars(self, lines: List[str]) -> List[List[str]]:
        """Резервная нарезка по символам (если нет временных меток)."""
        chunks: List[List[str]] = []
        current: List[str] = []
        current_len = 0
        for line in lines:
            ll = len(line) + 1
            if current_len + ll > MAX_CHUNK_CHARS and current:
                chunks.append(current)
                overlap = current[-CHUNK_OVERLAP_LINES:]
                current = list(overlap)
                current_len = sum(len(l) + 1 for l in current)
            current.append(line)
            current_len += ll
        if current:
            chunks.append(current)
        return chunks

    def _format_lines(self, transcript: TranscriptResult) -> List[str]:
        """Форматировать транскрипт в список строк с таймкодами и спикерами."""
        lines = []
        if transcript.segments:
            for seg in transcript.segments:
                if transcript.has_speakers and seg.speaker:
                    lines.append(f"[{seg.timecode}] {seg.speaker}: {seg.text}")
                else:
                    lines.append(f"[{seg.timecode}] {seg.text}")
        else:
            lines = [transcript.text]
        return lines

    def _analyze_chunked(
        self,
        meeting_id: str,
        title: str,
        transcript: TranscriptResult,
        lines: List[str],
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> AnalysisResult:
        """
        Разбить длинный транскрипт на чанки по временным интервалам,
        проанализировать каждый, смёржить результаты в один AnalysisResult.
        """
        # Разбиваем по времени (CHUNK_MINUTES минут), а не по символам
        chunks = self._split_by_time(transcript, lines)

        # Fallback: если сегментов нет — символьная нарезка
        if not chunks:
            chunks = self._split_by_chars(lines)
        else:
            # Дополнительно ограничиваем каждый временной чанк по символам,
            # чтобы не превысить контекстное окно LLM (4K токенов).
            # Длинный чанк (напр. 20 мин с 8 спикерами) может быть 30000+ символов —
            # это вызывает 400 Bad Request ("context overflow") от LM Studio.
            refined: list = []
            for chunk in chunks:
                if sum(len(l) + 1 for l in chunk) > MAX_CHUNK_CHARS:
                    refined.extend(self._split_by_chars(chunk))
                else:
                    refined.append(chunk)
            chunks = refined

        logger.info(
            f"[ANALYSIS] Длинный транскрипт → {len(chunks)} чанков "
            f"(~{len(lines)} строк, {sum(len(l) for l in lines)} символов)"
        )

        # Анализируем каждый чанк
        all_tasks: List[AnalysisTask] = []
        all_key_points: List[str] = []
        all_decisions: List[str] = []
        all_open_questions: List[str] = []
        all_participants: List[str] = []
        summaries: List[str] = []
        notes_parts: List[str] = []
        chunk_errors: List[str] = []
        chunk_titles: List[str] = []

        for i, chunk_lines in enumerate(chunks):
            chunk_text = "\n".join(chunk_lines)
            chunk_info = f"{i + 1}/{len(chunks)}"
            logger.info(f"[ANALYSIS] Чанк {chunk_info} ({len(chunk_text)} символов)...")
            if progress_cb:
                progress_cb(i, len(chunks))
            prompt = self._build_prompt(title, chunk_text, transcript.language, chunk_info)
            try:
                raw_json = self._call_llm(prompt)
                r = self._parse_response(raw_json, meeting_id, title, transcript)
                summaries.append(r.summary)
                all_key_points.extend(r.key_points)
                all_decisions.extend(r.decisions)
                all_open_questions.extend(r.open_questions)
                all_tasks.extend(r.tasks)
                all_participants.extend(r.participants)
                if r.notes_markdown:
                    notes_parts.append(f"### Часть {chunk_info}\n{r.notes_markdown}")
                if r.title and r.title != title:
                    chunk_titles.append(r.title)
                logger.info(f"[ANALYSIS] Чанк {chunk_info} ✓ ({len(r.key_points)} тезисов, {len(r.tasks)} задач)")
            except Exception as exc:
                logger.warning(f"[ANALYSIS] Чанк {chunk_info} — все попытки исчерпаны: {exc}")
                chunk_errors.append(f"Чанк {chunk_info}: {exc}")
                # Логируем временной диапазон пропущенного чанка для последующего аудита
                if chunk_lines:
                    first_tc = chunk_lines[0].split("]")[0].lstrip("[") if chunk_lines[0].startswith("[") else "?"
                    last_tc = chunk_lines[-1].split("]")[0].lstrip("[") if chunk_lines[-1].startswith("[") else "?"
                    logger.warning(f"[ANALYSIS] ⚠ Пропущен диапазон: {first_tc} — {last_tc}")

        # Если все чанки упали — сразу возвращаем ошибку
        if not summaries and chunk_errors:
            error_detail = "; ".join(chunk_errors[:3])
            raise RuntimeError(
                f"Все {len(chunks)} чанков завершились ошибкой. "
                f"Первые ошибки: {error_detail}"
            )

        # Мёрж-промпт: итоговое summary из всех саммари
        merged_summary = " ".join(s for s in summaries if s)
        if len(chunks) > 1 and summaries:
            try:
                merge_prompt = (
                    f"Объедини следующие краткие изложения отдельных частей встречи "
                    f"\"{title}\" в одно связное краткое изложение (3-5 предложений) на русском. "
                    f"Верни ТОЛЬКО текст, без JSON:\n\n"
                    + "\n\n".join(f"Часть {i+1}: {s}" for i, s in enumerate(summaries) if s)
                )
                raw = self._call_llm(merge_prompt, max_tokens=500)
                # _call_llm может вернуть JSON — попробуем извлечь текст
                try:
                    data = json.loads(raw)
                    merged_summary = data.get("summary", merged_summary)
                except json.JSONDecodeError:
                    merged_summary = raw.strip() or merged_summary
            except Exception as exc:
                logger.warning(f"[ANALYSIS] Мёрж summary не удался: {exc}")

        # Дедупликация
        def dedup(lst: List[str]) -> List[str]:
            seen, out = set(), []
            for x in lst:
                lx = x.lower().strip()
                if lx and lx not in seen:
                    seen.add(lx)
                    out.append(x)
            return out

        return AnalysisResult(
            meeting_id=meeting_id,
            title=chunk_titles[0] if chunk_titles else title,
            language=transcript.language,
            duration_sec=transcript.audio_duration_sec,
            participants=dedup(all_participants),
            summary=merged_summary,
            key_points=dedup(all_key_points),
            decisions=dedup(all_decisions),
            open_questions=dedup(all_open_questions),
            tasks=all_tasks,
            notes_markdown="\n\n".join(notes_parts),
        )

    def _format_for_llm(self, transcript: TranscriptResult) -> str:
        """Устаревший метод — используется _format_lines."""
        return "\n".join(self._format_lines(transcript))

    def _build_summary_md(self, result: AnalysisResult) -> str:
        """Генерация summary.md"""
        lines = [
            f"# {result.title}",
            "",
            f"**Язык:** {result.language}  ",
            f"**Длительность:** {_fmt_duration(result.duration_sec)}  ",
            f"**Участников:** {len(result.participants) or '—'}  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            result.summary or "_Нет данных_",
            "",
        ]

        if result.key_points:
            lines += ["## Ключевые тезисы", ""]
            for kp in result.key_points:
                lines.append(f"- {kp}")
            lines.append("")

        if result.decisions:
            lines += ["## Принятые решения", ""]
            for d in result.decisions:
                lines.append(f"- {d}")
            lines.append("")

        if result.open_questions:
            lines += ["## Открытые вопросы", ""]
            for q in result.open_questions:
                lines.append(f"- {q}")
            lines.append("")

        if result.tasks:
            lines += ["## Задачи", ""]
            for t in result.tasks:
                priority_label = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                    t.priority, "🟡"
                )
                assignee = f" (@{t.assignee})" if t.assignee else ""
                lines.append(f"- {priority_label} **{t.title}**{assignee}")
                if t.description:
                    lines.append(f"  {t.description}")
            lines.append("")

        if result.notes_markdown:
            lines += ["## Заметки", "", result.notes_markdown, ""]

        return "\n".join(lines)


def _fmt_duration(sec: float) -> str:
    total = int(sec)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}ч {m}м {s}с"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"
