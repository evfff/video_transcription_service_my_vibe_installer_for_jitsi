'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import {
  listMeetings,
  scanInbox,
  getWatcherStatus,
  formatDuration,
  statusColor,
  type MeetingListItem,
  type WatcherStatus,
} from '@/lib/api/meetingsApi'
import {
  Video,
  Search,
  RefreshCw,
  ScanLine,
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileText,
  Brain,
  BookOpen,
  Users,
  ListTodo,
  ChevronRight,
  Wifi,
  WifiOff,
} from 'lucide-react'

const STATUS_OPTIONS = [
  { value: 'all', label: 'Все статусы' },
  { value: 'detected', label: 'Обнаружена' },
  { value: 'queued', label: 'В очереди' },
  { value: 'processing', label: 'Обрабатывается' },
  { value: 'transcribing', label: 'Транскрибация' },
  { value: 'analyzing', label: 'Анализ' },
  { value: 'completed', label: 'Завершена' },
  { value: 'partial_completed', label: 'Частично' },
  { value: 'failed', label: 'Ошибка' },
]

export function MeetingsView() {
  const { toast } = useToast()

  const [meetings, setMeetings] = useState<MeetingListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [watcher, setWatcher] = useState<WatcherStatus | null>(null)

  const loadMeetings = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listMeetings({
        search: search || undefined,
        status: statusFilter !== 'all' ? statusFilter : undefined,
        limit: 100,
      })
      setMeetings(data.meetings)
      setTotal(data.total)
    } catch (err) {
      toast({
        title: 'Ошибка',
        description: err instanceof Error ? err.message : 'Не удалось загрузить встречи',
        variant: 'destructive',
      })
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter, toast])

  const loadWatcherStatus = useCallback(async () => {
    try {
      const status = await getWatcherStatus()
      setWatcher(status)
    } catch {
      // watcher статус необязателен
    }
  }, [])

  useEffect(() => {
    loadMeetings()
    loadWatcherStatus()
  }, [loadMeetings, loadWatcherStatus])

  // Автообновление каждые 10 сек если есть активные
  useEffect(() => {
    const hasActive = meetings.some(
      (m) => !['completed', 'partial_completed', 'failed', 'detected', 'queued'].includes(m.status)
    )
    if (!hasActive) return
    const timer = setInterval(loadMeetings, 10000)
    return () => clearInterval(timer)
  }, [meetings, loadMeetings])

  const handleScan = async () => {
    setScanning(true)
    try {
      const result = await scanInbox()
      if (result.new_meetings > 0) {
        toast({
          title: 'Сканирование завершено',
          description: `Обнаружено новых встреч: ${result.new_meetings}`,
        })
        loadMeetings()
      } else {
        toast({ title: 'Нет новых встреч', description: 'Inbox не содержит новых папок встреч' })
      }
    } catch (err) {
      toast({
        title: 'Ошибка сканирования',
        description: err instanceof Error ? err.message : 'Неизвестная ошибка',
        variant: 'destructive',
      })
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Video className="h-6 w-6" />
            Встречи
          </h1>
          <p className="text-muted-foreground mt-1">
            Обработка и анализ записей встреч
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadMeetings} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Обновить
          </Button>
          <Button size="sm" onClick={handleScan} disabled={scanning}>
            {scanning ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <ScanLine className="h-4 w-4 mr-2" />
            )}
            Сканировать inbox
          </Button>
        </div>
      </div>

      {/* Watcher status */}
      {watcher && (
        <div className="flex items-center gap-3 text-sm text-muted-foreground bg-muted/30 rounded-lg px-4 py-2">
          {watcher.running ? (
            <Wifi className="h-4 w-4 text-green-500" />
          ) : (
            <WifiOff className="h-4 w-4 text-red-500" />
          )}
          <span>
            Watcher{' '}
            <span className={watcher.running ? 'text-green-500' : 'text-red-500'}>
              {watcher.running ? 'работает' : 'остановлен'}
            </span>
          </span>
          <span className="text-muted-foreground/60">•</span>
          <span>Inbox: <code className="text-xs">{watcher.inbox_path}</code></span>
          <span className="text-muted-foreground/60">•</span>
          <span>Всего: {watcher.total_meetings}</span>
          {watcher.processing_count > 0 && (
            <>
              <span className="text-muted-foreground/60">•</span>
              <span className="text-yellow-500">
                В обработке: {watcher.processing_count}
              </span>
            </>
          )}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Поиск по названию..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Статус" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground self-center">
          {total} встреч
        </span>
      </div>

      {/* Empty state */}
      {!loading && meetings.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Video className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="font-semibold text-lg mb-2">Встреч не найдено</h3>
            <p className="text-muted-foreground max-w-sm">
              Положите папку встречи в inbox и нажмите «Сканировать inbox».
            </p>
            <Button className="mt-4" onClick={handleScan} disabled={scanning}>
              <ScanLine className="h-4 w-4 mr-2" />
              Сканировать inbox
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Meetings list */}
      {!loading && meetings.length > 0 && (
        <div className="grid gap-3">
          {meetings.map((meeting) => (
            <MeetingCard key={meeting.id} meeting={meeting} />
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================================
// Meeting Card
// ============================================================================

function MeetingCard({ meeting }: { meeting: MeetingListItem }) {
  const isActive = !['completed', 'partial_completed', 'failed', 'detected', 'queued'].includes(
    meeting.status
  )

  return (
    <Link href={`/meetings/${meeting.id}`} className="block group">
      <Card className="hover:border-primary/50 transition-colors cursor-pointer">
        <CardContent className="p-4">
          <div className="flex items-start gap-4">
            {/* Icon */}
            <div className="mt-0.5">
              <StatusIcon status={meeting.status} />
            </div>

            {/* Main info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold truncate group-hover:text-primary transition-colors">
                    {meeting.title || meeting.folder_name}
                  </h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    {meeting.folder_name}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <StatusBadge status={meeting.status} label={meeting.status_label} />
                  <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-foreground transition-colors" />
                </div>
              </div>

              {/* Meta info row */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  {new Date(meeting.created_at).toLocaleDateString('ru')}
                </span>
                {meeting.duration_sec > 0 && (
                  <span>{formatDuration(meeting.duration_sec)}</span>
                )}
                {meeting.source_files_count > 0 && (
                  <span>{meeting.source_files_count} файл(ов)</span>
                )}
                {meeting.language && (
                  <span className="uppercase">{meeting.language}</span>
                )}
                {meeting.speaker_count > 0 && (
                  <span className="flex items-center gap-1">
                    <Users className="h-3.5 w-3.5" />
                    {meeting.speaker_count}
                  </span>
                )}
                {meeting.task_count > 0 && (
                  <span className="flex items-center gap-1">
                    <ListTodo className="h-3.5 w-3.5" />
                    {meeting.task_count}
                  </span>
                )}
              </div>

              {/* Artifact badges */}
              <div className="flex gap-2 mt-2">
                <ArtifactBadge label="Транскрипт" available={meeting.has_transcript} icon={FileText} />
                <ArtifactBadge label="Анализ" available={meeting.has_analysis} icon={Brain} />
                <ArtifactBadge label="Obsidian" available={meeting.has_obsidian} icon={BookOpen} />
              </div>

              {/* Error message */}
              {meeting.last_error && meeting.status === 'failed' && (
                <div className="mt-2 flex items-start gap-1.5 text-xs text-red-500">
                  <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                  <span className="truncate">{meeting.last_error}</span>
                </div>
              )}

              {/* Active indicator */}
              {isActive && (
                <div className="mt-2 flex items-center gap-2 text-xs text-yellow-500">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {meeting.status_label}...
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

// ============================================================================
// Sub-components
// ============================================================================

function StatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 className="h-5 w-5 text-green-500" />
  if (status === 'failed') return <AlertCircle className="h-5 w-5 text-red-500" />
  if (status === 'partial_completed') return <AlertCircle className="h-5 w-5 text-orange-500" />
  if (['detected', 'queued'].includes(status)) return <Clock className="h-5 w-5 text-muted-foreground" />
  return <Loader2 className="h-5 w-5 text-yellow-500 animate-spin" />
}

function StatusBadge({ status, label }: { status: string; label: string }) {
  const variants: Record<string, string> = {
    completed: 'bg-green-500/15 text-green-600 border-green-500/30',
    partial_completed: 'bg-orange-500/15 text-orange-600 border-orange-500/30',
    failed: 'bg-red-500/15 text-red-600 border-red-500/30',
    queued: 'bg-blue-500/15 text-blue-600 border-blue-500/30',
    detected: 'bg-muted text-muted-foreground border-border',
  }
  const cls =
    variants[status] ||
    'bg-yellow-500/15 text-yellow-600 border-yellow-500/30'

  return (
    <span className={`text-xs border px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {label}
    </span>
  )
}

function ArtifactBadge({
  label,
  available,
  icon: Icon,
}: {
  label: string
  available: boolean
  icon: React.ComponentType<{ className?: string }>
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border ${
        available
          ? 'text-green-600 border-green-500/30 bg-green-500/10'
          : 'text-muted-foreground border-border bg-muted/30'
      }`}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  )
}
