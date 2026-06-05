'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/ui/use-toast'
import {
  getMeeting,
  reprocessMeeting,
  exportToObsidian,
  formatDuration,
  type MeetingDetail,
  type TranscriptSegment,
} from '@/lib/api/meetingsApi'
import {
  ArrowLeft,
  RefreshCw,
  BookOpen,
  Brain,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Clock,
  Users,
  ListTodo,
  FileText,
  Video,
  ChevronDown,
  ChevronRight,
  Copy,
  Folder,
} from 'lucide-react'

interface MeetingDetailViewProps {
  meetingId: string
}

export function MeetingDetailView({ meetingId }: MeetingDetailViewProps) {
  const { toast } = useToast()
  const [detail, setDetail] = useState<MeetingDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [rawOpen, setRawOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await getMeeting(meetingId)
      setDetail(data)
    } catch (err) {
      toast({
        title: 'Ошибка',
        description: err instanceof Error ? err.message : 'Не удалось загрузить встречу',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [meetingId, toast])

  useEffect(() => {
    load()
  }, [load])

  // Auto-refresh if processing
  useEffect(() => {
    if (!detail) return
    const isActive = !['completed', 'partial_completed', 'failed', 'detected', 'queued'].includes(
      detail.meta.status
    )
    if (!isActive) return
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [detail, load])

  const handleReprocess = async (fromStage: string = 'start') => {
    setActionLoading('reprocess')
    try {
      await reprocessMeeting(meetingId, fromStage)
      toast({ title: 'Обработка запущена', description: `С этапа: ${fromStage}` })
      setTimeout(load, 2000)
    } catch (err) {
      toast({
        title: 'Ошибка',
        description: err instanceof Error ? err.message : 'Не удалось запустить обработку',
        variant: 'destructive',
      })
    } finally {
      setActionLoading(null)
    }
  }

  const handleExport = async () => {
    setActionLoading('export')
    try {
      await exportToObsidian(meetingId)
      toast({ title: 'Экспортировано в Obsidian', description: 'Заметка сохранена в vault' })
      load()
    } catch (err) {
      toast({
        title: 'Ошибка экспорта',
        description: err instanceof Error ? err.message : 'Не удалось экспортировать',
        variant: 'destructive',
      })
    } finally {
      setActionLoading(null)
    }
  }

  const handleAnalyze = async () => {
    setActionLoading('analysis')
    try {
      await reprocessMeeting(meetingId, 'analysis')
      toast({ title: 'Анализ запущен', description: 'LLM анализирует содержание встречи...' })
      setTimeout(load, 2000)
    } catch (err) {
      toast({
        title: 'Ошибка',
        description: err instanceof Error ? err.message : 'Не удалось запустить анализ',
        variant: 'destructive',
      })
    } finally {
      setActionLoading(null)
    }
  }

  const handleDiarize = async () => {
    setActionLoading('diarization')
    try {
      await reprocessMeeting(meetingId, 'diarization')
      toast({ title: 'Диаризация запущена', description: 'Разделение по спикерам...' })
      setTimeout(load, 2000)
    } catch (err) {
      toast({
        title: 'Ошибка',
        description: err instanceof Error ? err.message : 'Не удалось запустить диаризацию',
        variant: 'destructive',
      })
    } finally {
      setActionLoading(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="text-center py-16">
        <AlertCircle className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
        <p className="text-muted-foreground">Встреча не найдена</p>
        <Link href="/meetings">
          <Button variant="outline" className="mt-4">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Назад к списку
          </Button>
        </Link>
      </div>
    )
  }

  const { meta, transcript, analysis, artifacts } = detail
  const isActive = !['completed', 'partial_completed', 'failed', 'detected', 'queued'].includes(
    meta.status
  )

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/meetings" className="hover:text-foreground transition-colors flex items-center gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Встречи
        </Link>
        <ChevronRight className="h-3.5 w-3.5" />
        <span className="text-foreground truncate max-w-xs">
          {meta.title || meta.folder_name}
        </span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold truncate">
            {meta.title || meta.folder_name}
          </h1>
          <p className="text-muted-foreground text-sm mt-1 flex items-center gap-1.5">
            <Folder className="h-3.5 w-3.5" />
            {meta.folder_name}
          </p>
        </div>

        {/* Actions */}
        <div className="flex gap-2 shrink-0 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleReprocess('start')}
            disabled={!!actionLoading || isActive}
            title="Перезапустить полную обработку"
          >
            {actionLoading === 'reprocess' ? (
              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            ) : (
              <RotateCcw className="h-4 w-4 mr-1.5" />
            )}
            Обработать
          </Button>

          {meta.transcript_status === 'done' && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleDiarize}
              disabled={!!actionLoading || isActive}
              title="Разделить речь по спикерам (без повторной транскрибации)"
            >
              {actionLoading === 'diarization' ? (
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              ) : (
                <Users className="h-4 w-4 mr-1.5" />
              )}
              {meta.diarization_status === 'done' ? 'Обновить спикеров' : 'Спикеры'}
            </Button>
          )}

          {meta.transcript_status === 'done' && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleAnalyze}
              disabled={!!actionLoading || isActive}
              title="Запустить LLM анализ содержания"
            >
              {actionLoading === 'analysis' ? (
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              ) : (
                <Brain className="h-4 w-4 mr-1.5" />
              )}
              {meta.analysis_status === 'done' ? 'Обновить анализ' : 'Анализировать'}
            </Button>
          )}

          <Button
            size="sm"
            onClick={handleExport}
            disabled={!!actionLoading || meta.documents_status !== 'done'}
            title={meta.documents_status !== 'done' ? 'Сначала дождитесь генерации документов' : ''}
          >
            {actionLoading === 'export' ? (
              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            ) : (
              <BookOpen className="h-4 w-4 mr-1.5" />
            )}
            В Obsidian
          </Button>
        </div>
      </div>

      {/* Status bar */}
      <PipelineStatusBar meta={meta} />

      {/* Active processing indicator */}
      {isActive && (
        <div className="flex items-center gap-2 text-sm text-yellow-500 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-4 py-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Обработка: {meta.status.replace(/_/g, ' ')}...
        </div>
      )}

      {/* Error state */}
      {meta.last_error && meta.status === 'failed' && (
        <div className="flex items-start gap-2 text-sm text-red-500 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">Ошибка обработки</div>
            <div className="mt-0.5 text-red-400">{meta.last_error}</div>
          </div>
        </div>
      )}

      {/* Stage errors */}
      {Object.keys(meta.stage_errors || {}).length > 0 && (
        <div className="space-y-1">
          {Object.entries(meta.stage_errors).map(([stage, err]) => (
            <div
              key={stage}
              className="flex items-start gap-2 text-xs text-orange-500 bg-orange-500/10 border border-orange-500/20 rounded px-3 py-1.5"
            >
              <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>
                <strong>{stage}:</strong> {err}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Main info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetaCard
          icon={Clock}
          label="Дата"
          value={new Date(meta.created_at).toLocaleDateString('ru')}
        />
        <MetaCard
          icon={Video}
          label="Длительность"
          value={meta.duration_sec > 0 ? formatDuration(meta.duration_sec) : '—'}
        />
        <MetaCard
          icon={Users}
          label="Спикеров"
          value={meta.speaker_count > 0 ? String(meta.speaker_count) : '—'}
        />
        <MetaCard
          icon={ListTodo}
          label="Задач"
          value={meta.task_count > 0 ? String(meta.task_count) : '—'}
        />
      </div>

      {/* Source files */}
      {meta.source_files.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Исходные файлы
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="flex flex-wrap gap-2">
              {meta.source_files.map((f) => (
                <span
                  key={f}
                  className="text-xs bg-muted px-2 py-1 rounded font-mono border border-border"
                >
                  {f}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabs: Summary | Transcript | Tasks | Notes | Artifacts */}
      <Tabs defaultValue={analysis ? 'summary' : transcript ? 'transcript' : 'artifacts'}>
        <TabsList className="flex-wrap h-auto">
          <TabsTrigger value="summary" disabled={!analysis}>
            <Brain className="h-3.5 w-3.5 mr-1.5" />
            Summary
          </TabsTrigger>
          <TabsTrigger value="transcript" disabled={!transcript}>
            <FileText className="h-3.5 w-3.5 mr-1.5" />
            Транскрипт
          </TabsTrigger>
          <TabsTrigger value="tasks" disabled={!analysis || !analysis.tasks.length}>
            <ListTodo className="h-3.5 w-3.5 mr-1.5" />
            Задачи {analysis?.tasks.length ? `(${analysis.tasks.length})` : ''}
          </TabsTrigger>
          <TabsTrigger value="notes" disabled={!analysis?.notes_markdown}>
            Заметки
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            Артефакты{artifacts.length > 0 ? ` (${artifacts.length})` : ''}
          </TabsTrigger>
        </TabsList>

        {/* Summary tab */}
        <TabsContent value="summary" className="space-y-4">
          {analysis && (
            <>
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-medium">Краткое изложение</CardTitle>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-sm leading-relaxed">{analysis.summary || '—'}</p>
                </CardContent>
              </Card>

              {analysis.key_points.length > 0 && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-medium">Ключевые тезисы</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <ul className="space-y-1.5">
                      {analysis.key_points.map((kp, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="shrink-0 text-muted-foreground">•</span>
                          {kp}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {analysis.decisions.length > 0 && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-medium">Принятые решения</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <ul className="space-y-1.5">
                      {analysis.decisions.map((d, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0 mt-0.5" />
                          {d}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {analysis.open_questions.length > 0 && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-medium">Открытые вопросы</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <ul className="space-y-1.5">
                      {analysis.open_questions.map((q, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="shrink-0 text-orange-500">?</span>
                          {q}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </TabsContent>

        {/* Transcript tab */}
        <TabsContent value="transcript">
          {transcript && (
            <Card>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-medium">
                    Транскрипт — {transcript.segments.length} сегментов
                    {transcript.language && (
                      <span className="ml-2 text-muted-foreground font-normal uppercase">
                        {transcript.language}
                      </span>
                    )}
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <ScrollArea className="h-[500px] pr-3">
                  <div className="space-y-3">
                    {transcript.segments.map((seg, i) => (
                      <TranscriptSegmentItem key={i} segment={seg} />
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Tasks tab */}
        <TabsContent value="tasks">
          {analysis && analysis.tasks.length > 0 && (
            <div className="space-y-2">
              {analysis.tasks.map((task, i) => (
                <Card key={i}>
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <PriorityBadge priority={task.priority} />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-sm">{task.title}</div>
                        {task.description && (
                          <p className="text-sm text-muted-foreground mt-0.5">{task.description}</p>
                        )}
                        <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 text-xs text-muted-foreground">
                          {task.assignee && <span>@{task.assignee}</span>}
                          {task.due_date && <span>📅 {task.due_date}</span>}
                          {task.timecode && <span className="font-mono">{task.timecode}</span>}
                          {task.speaker && <span>{task.speaker}</span>}
                        </div>
                        {task.source_fragment && (
                          <blockquote className="mt-2 text-xs text-muted-foreground border-l-2 border-border pl-2 italic truncate">
                            «{task.source_fragment}»
                          </blockquote>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Notes tab */}
        <TabsContent value="notes">
          {analysis?.notes_markdown && (
            <Card>
              <CardContent className="p-4">
                <pre className="text-sm whitespace-pre-wrap font-sans leading-relaxed">
                  {analysis.notes_markdown}
                </pre>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Artifacts tab */}
        <TabsContent value="artifacts">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Файлы артефактов</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {artifacts.length === 0 ? (
                <p className="text-sm text-muted-foreground">Артефакты ещё не созданы</p>
              ) : (
                <div className="space-y-1">
                  {artifacts.map((f) => (
                    <div
                      key={f}
                      className="flex items-center gap-2 text-sm py-1.5 border-b border-border/50 last:border-0"
                    >
                      <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <span className="font-mono text-xs">{f}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Raw JSON toggle */}
          <button
            className="w-full text-left text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-2 mt-3"
            onClick={() => setRawOpen(!rawOpen)}
          >
            {rawOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            Сырые данные (JSON)
          </button>
          {rawOpen && (
            <Card className="mt-2">
              <CardContent className="p-4">
                <pre className="text-xs leading-relaxed overflow-auto max-h-96 text-muted-foreground">
                  {JSON.stringify(detail, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ============================================================================
// Sub-components
// ============================================================================

function PipelineStatusBar({ meta }: { meta: MeetingDetail['meta'] }) {
  const stages = [
    { key: 'audio', label: 'Аудио', done: meta.audio_extracted, failed: !!meta.stage_errors?.audio },
    {
      key: 'transcript',
      label: 'Транскрипт',
      done: meta.transcript_status === 'done',
      failed: meta.transcript_status === 'failed',
    },
    {
      key: 'diarization',
      label: 'Спикеры',
      done: meta.diarization_status === 'done',
      failed: meta.diarization_status === 'failed',
      skipped: meta.diarization_status === 'skipped',
    },
    {
      key: 'analysis',
      label: 'Анализ',
      done: meta.analysis_status === 'done',
      failed: meta.analysis_status === 'failed',
    },
    {
      key: 'documents',
      label: 'Документы',
      done: meta.documents_status === 'done',
      failed: meta.documents_status === 'failed',
    },
    {
      key: 'obsidian',
      label: 'Obsidian',
      done: meta.obsidian_status === 'done',
      failed: meta.obsidian_status === 'failed',
      skipped: meta.obsidian_status === 'pending' && meta.status === 'completed',
    },
  ]

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {stages.map((stage, i) => (
        <div key={stage.key} className="flex items-center gap-1">
          <div
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded border ${
              stage.done
                ? 'text-green-600 border-green-500/30 bg-green-500/10'
                : stage.failed
                ? 'text-red-500 border-red-500/30 bg-red-500/10'
                : stage.skipped
                ? 'text-muted-foreground border-border bg-muted/30'
                : 'text-muted-foreground border-border bg-transparent'
            }`}
          >
            {stage.done ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : stage.failed ? (
              <AlertCircle className="h-3 w-3" />
            ) : null}
            {stage.label}
          </div>
          {i < stages.length - 1 && (
            <ChevronRight className="h-3 w-3 text-muted-foreground/50" />
          )}
        </div>
      ))}
    </div>
  )
}

function MetaCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
}) {
  return (
    <div className="bg-muted/30 border border-border rounded-lg p-3">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="font-semibold text-sm">{value}</div>
    </div>
  )
}

function TranscriptSegmentItem({ segment }: { segment: TranscriptSegment }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(segment.text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="group flex gap-3">
      <div className="shrink-0 font-mono text-xs text-muted-foreground pt-0.5 w-16 text-right">
        {segment.timecode}
      </div>
      {segment.speaker && (
        <div className="shrink-0 text-xs font-medium text-primary/70 pt-0.5 w-20 truncate">
          {segment.speaker}
        </div>
      )}
      <div className="flex-1 text-sm leading-relaxed relative">
        {segment.text}
        <button
          onClick={handleCopy}
          className="absolute right-0 top-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5"
          title="Скопировать"
        >
          <Copy className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
      </div>
    </div>
  )
}

function PriorityBadge({ priority }: { priority: string }) {
  const config: Record<string, { label: string; cls: string }> = {
    high: { label: '🔴 Высокий', cls: 'text-red-500 bg-red-500/10 border-red-500/30' },
    medium: { label: '🟡 Средний', cls: 'text-yellow-600 bg-yellow-500/10 border-yellow-500/30' },
    low: { label: '🟢 Низкий', cls: 'text-green-600 bg-green-500/10 border-green-500/30' },
  }
  const { label, cls } = config[priority] || config.medium
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border font-medium shrink-0 ${cls}`}>
      {label}
    </span>
  )
}
